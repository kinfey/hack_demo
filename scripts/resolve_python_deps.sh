#!/usr/bin/env bash
set -euo pipefail

rm -rf .azure/python-deps
uv pip install \
  --target .azure/python-deps \
  --python-platform x86_64-manylinux_2_34 \
  --python-version 3.12 \
  --index-url https://packagefeedproxy.microsoft.io/pypi/simple \
  agent-framework-core==1.12.0 \
  agent-framework-github-copilot==1.0.0rc4 \
  github-copilot-sdk==1.0.2 \
  mcp==1.28.1 \
  openpyxl==3.1.5 \
  'pydantic>=2.11,<3' \
  'python-dotenv>=1.1,<2' \
  'starlette>=0.46,<1' \
  'uvicorn>=0.34,<1'
