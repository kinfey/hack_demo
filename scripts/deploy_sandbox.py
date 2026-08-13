from __future__ import annotations

import base64
import io
import json
import os
import sys
import tarfile
import time
import urllib.request
import uuid
from pathlib import Path

from azure.containerapps.sandbox import (
    SandboxGroupClient,
    SandboxGroupManagementClient,
    endpoint_for_region,
)
from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.authorization import AuthorizationManagementClient
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "rg-budget-agent")
SANDBOX_GROUP = os.getenv("ACA_SANDBOX_GROUP", "aca-sbx-budget-agent")
REGION = os.getenv("AZURE_LOCATION", "eastus2")
PORT = 8000
SANDBOX_DATA_OWNER_ROLE_ID = "c24cf47c-5077-412d-a19c-45202126392c"


def archive() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        for relative in ("pyproject.toml", "budget_agent"):
            bundle.add(ROOT / relative, arcname=relative)
    return output.getvalue()


def mcp_initialize(url: str) -> dict:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "budget-agent-deployer", "version": "0.1.0"},
            },
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def token_principal_id(credential: DefaultAzureCredential) -> str:
    token = credential.get_token("https://management.azure.com/.default").token
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    principal_id = claims.get("oid")
    if not principal_id:
        raise RuntimeError("The Azure access token does not contain an object ID claim.")
    return principal_id


def ensure_sandbox_data_owner(
    credential: DefaultAzureCredential,
    subscription_id: str,
) -> None:
    scope = (
        f"/subscriptions/{subscription_id}/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.App/sandboxGroups/{SANDBOX_GROUP}"
    )
    role_definition_id = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/"
        f"roleDefinitions/{SANDBOX_DATA_OWNER_ROLE_ID}"
    )
    principal_id = token_principal_id(credential)
    assignment_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}:{principal_id}:{role_definition_id}"))
    authorization = AuthorizationManagementClient(credential, subscription_id)
    try:
        authorization.role_assignments.create(
            scope,
            assignment_id,
            RoleAssignmentCreateParameters(
                role_definition_id=role_definition_id,
                principal_id=principal_id,
            ),
        )
    finally:
        authorization.close()


def main() -> int:
    token = os.getenv("COPILOT_GITHUB_TOKEN")
    if not token:
        sys.exit("COPILOT_GITHUB_TOKEN is required for headless GitHub Copilot SDK authentication.")
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    if not subscription_id:
        sys.exit("AZURE_SUBSCRIPTION_ID is required.")

    credential = DefaultAzureCredential()
    management = SandboxGroupManagementClient(
        credential,
        subscription_id=subscription_id,
        resource_group=RESOURCE_GROUP,
    )
    try:
        management.get_group(SANDBOX_GROUP)
    except HttpResponseError as error:
        if error.status_code != 404:
            raise
        management.create_group(
            SANDBOX_GROUP,
            REGION,
            tags={"project": "engineering-budget-agent", "environment": "hack"},
        )
    ensure_sandbox_data_owner(credential, subscription_id)

    group = SandboxGroupClient(
        endpoint_for_region(REGION),
        credential,
        subscription_id=subscription_id,
        resource_group=RESOURCE_GROUP,
        sandbox_group=SANDBOX_GROUP,
    )
    sandbox = group.begin_create_sandbox(
        disk="copilot",
        cpu="2000m",
        memory="4096Mi",
        auto_suspend_seconds=3600,
        labels={"name": SANDBOX_GROUP, "service": "budget-mcp"},
        environment={
            "COPILOT_GITHUB_TOKEN": token,
            "GITHUB_COPILOT_MODEL": "gpt-5.6-sol",
            "PORT": str(PORT),
        },
    ).result()
    sandbox.write_file("/home/user/budget-agent.tar.gz", archive())
    commands = [
        "mkdir -p /home/user/budget-agent",
        "tar -xzf /home/user/budget-agent.tar.gz -C /home/user/budget-agent",
    ]
    for command in commands:
        result = sandbox.exec(command)
        if result.exit_code != 0:
            raise RuntimeError(f"Sandbox command failed: {command}\n{result.stdout}\n{result.stderr}")

    install_command = (
        "cd /home/user/budget-agent && "
        "nohup sh -c '"
        "python3 -m pip install --target /home/user/budget-agent/.packages "
        "--index-url https://packagefeedproxy.microsoft.io/pypi/simple "
        "agent-framework-core==1.12.0 "
        "agent-framework-github-copilot==1.0.0rc4 "
        "github-copilot-sdk==1.0.2 "
        "mcp==1.28.1 openpyxl==3.1.5 "
        "\"pydantic>=2.11,<3\" \"python-dotenv>=1.1,<2\" "
        "\"starlette>=0.46,<1\" \"uvicorn>=0.34,<1\"; "
        "echo $? >/tmp/budget-install.exit"
        "' >/tmp/budget-install.log 2>&1 &"
    )
    result = sandbox.exec(install_command)
    if result.exit_code != 0:
        raise RuntimeError(
            f"Sandbox dependency installation failed to start:\n{result.stdout}\n{result.stderr}"
        )

    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        result = sandbox.exec("test -f /tmp/budget-install.exit && cat /tmp/budget-install.exit")
        if result.exit_code == 0:
            if result.stdout.strip() != "0":
                logs = sandbox.exec("tail -100 /tmp/budget-install.log")
                raise RuntimeError(f"Sandbox dependency installation failed:\n{logs.stdout}")
            break
        time.sleep(5)
    else:
        logs = sandbox.exec("tail -100 /tmp/budget-install.log")
        raise RuntimeError(f"Sandbox dependency installation timed out:\n{logs.stdout}")

    commands = [
        (
            "cd /home/user/budget-agent && "
            "nohup env PYTHONPATH=/home/user/budget-agent/.packages "
            "python3 -m budget_agent.server >/tmp/budget-agent.log 2>&1 "
            "& echo $! >/tmp/budget-agent.pid"
        ),
    ]
    for command in commands:
        result = sandbox.exec(command)
        if result.exit_code != 0:
            raise RuntimeError(f"Sandbox command failed: {command}\n{result.stdout}\n{result.stderr}")

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = sandbox.exec(f"curl -fsS http://localhost:{PORT}/healthz")
        if result.exit_code == 0:
            break
        time.sleep(3)
    else:
        logs = sandbox.exec("tail -100 /tmp/budget-agent.log")
        raise RuntimeError(f"MCP service did not become ready:\n{logs.stdout}\n{logs.stderr}")

    public_port = sandbox.add_port(PORT, anonymous=True)
    mcp_url = public_port.url.rstrip("/") + "/mcp"
    initialize = mcp_initialize(mcp_url)
    state = {
        "sandbox_group": SANDBOX_GROUP,
        "sandbox_id": sandbox.sandbox_id,
        "mcp_url": mcp_url,
        "initialize": initialize,
    }
    output = ROOT / ".azure" / "sandbox-deployment.json"
    output.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps(state, indent=2))
    group.close()
    management.close()
    credential.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
