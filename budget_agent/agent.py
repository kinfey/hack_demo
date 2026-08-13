from __future__ import annotations

import json
import os

from agent_framework.github import GitHubCopilotAgent, GitHubCopilotOptions
from copilot.generated.rpc import PermissionDecisionReject

from budget_agent.models import BudgetEvaluation

MODEL = os.getenv("GITHUB_COPILOT_MODEL", "gpt-5.6-sol")

INSTRUCTIONS = """
You are a senior quantity-surveying and engineering-budget review agent.
Use only the supplied deterministic evaluation JSON. Never invent prices, categories, or mappings.
All unit rates are USD per Sqm. Explain:
1. Page 1: vendor total price versus PER Budget using ±10% approval and ±20% conditional thresholds;
2. Page 2: mapped vendor category price versus QS Estimate using ±5% reasonable and ±15% review thresholds;
3. Page 3: mapped vendor unit rate versus historical unit rate using the same ±5% and ±15% thresholds.
Use the report traffic lights consistently: green means approve/reasonable, yellow means conditional/review,
red means reject/significant concern, and gray means benchmark missing.
Call out missing benchmarks and unmapped items explicitly. Recommend the commercially strongest vendor,
but identify category-level risks and negotiation targets. Respond in the user's language.
""".strip()


def deny_permission(_request: object, _invocation: dict[str, str]) -> PermissionDecisionReject:
    return PermissionDecisionReject(feedback="This read-only budget agent does not grant external actions.")


async def create_executive_summary(report: BudgetEvaluation, language: str = "zh-CN") -> str:
    agent = GitHubCopilotAgent(
        instructions=INSTRUCTIONS,
        name="EngineeringBudgetAgent",
        description="Evaluates engineering quotations against PER, QS, and historical Sqm benchmarks.",
        default_options=GitHubCopilotOptions(
            model=MODEL,
            timeout=float(os.getenv("GITHUB_COPILOT_TIMEOUT", "180")),
            on_permission_request=deny_permission,
        ),
    )
    payload = report.model_dump(exclude={"executive_summary"})
    prompt = (
        f"Output language: {language}.\n"
        "Prepare a concise executive recommendation from this evaluation JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    async with agent:
        result = await agent.run(prompt)
    return str(result)


async def answer_report_question(
    report: BudgetEvaluation,
    question: str,
    language: str = "zh-CN",
) -> str:
    agent = GitHubCopilotAgent(
        instructions=INSTRUCTIONS,
        name="EngineeringBudgetAgent",
        default_options=GitHubCopilotOptions(
            model=MODEL,
            timeout=float(os.getenv("GITHUB_COPILOT_TIMEOUT", "180")),
            on_permission_request=deny_permission,
        ),
    )
    prompt = (
        f"Output language: {language}.\n"
        f"Question: {question}\n"
        f"Evaluation JSON: {report.model_dump_json(exclude={'executive_summary'})}"
    )
    async with agent:
        result = await agent.run(prompt)
    return str(result)
