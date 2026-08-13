# Engineering Budget Evaluation Agent

Microsoft Agent Framework + GitHub Copilot SDK (`gpt-5.6-sol`) solution for evaluating engineering
budget workbooks through MCP and Microsoft Teams.

The calculation layer is deterministic. It reads `PER Budget`, `QS Estimation`, `Vendor Quotation`,
`MAPPING RULES`, `Historical Unit Rates`, and `Summary`; maps every priced vendor WBS row; and
normalizes category and total rates to USD/Sqm. GPT-5.6 Sol produces the executive narrative and
answers follow-up questions from the structured results.

## Architecture

```text
┌───────────────────────────────┐
│  User / Microsoft Teams      │
│  Uploads engineering Excel   │
│  workbook for budget review   │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  Teams App                    │
│  - Receives file attachment   │
│  - Downloads workbook         │
│  - Stores conversation report │
│  - Sends follow-up questions  │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  MCP Client                   │
│  - Calls evaluate_budget_     │
│    workbook tool              │
│  - Calls ask_budget_report    │
│  - Uses Streamable HTTP      │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  Budget Evaluation MCP        │
│  - /mcp endpoint             │
│  - Validates workbook         │
│  - Caches reports            │
│  - Returns structured data   │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  Deterministic Evaluation     │
│  - Reads PER / QS / History  │
│  - Maps vendor WBS rows      │
│  - Normalizes USD/Sqm        │
│  - Calculates variance       │
│  - Produces vendor decisions  │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  Structured Report Model     │
│  - Project metadata          │
│  - Vendor totals              │
│  - Category comparisons       │
│  - Warnings and unmatched     │
│    items                     │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  AI Summary Layer             │
│  - GitHub Copilot model      │
│  - Generates executive       │
│    recommendation            │
│  - Answers follow-up Q&A     │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  Response Back to User       │
│  - Evaluation card           │
│  - Summary narrative         │
│  - Chat follow-up answers    │
└───────────────────────────────┘
```

### Key components

- `teams_app/` — Microsoft Teams bot and UI integration
- `budget_agent/server.py` — MCP server exposing evaluation and report-query tools
- `budget_agent/evaluator.py` — Excel validation and deterministic cost comparison logic
- `budget_agent/agent.py` — GitHub Copilot-based narrative and Q&A generation
- `tests/` — validation and regression tests for evaluator behavior

## Evaluation rules

- Vendor total versus PER Budget:
  - `|variance| <= 10%`: approve
  - `10% < |variance| <= 20%`: conditional approval
  - `|variance| > 20%`: reject
- Vendor mapped category versus QS Estimate:
  - `|variance| <= 5%`: reasonable
  - `5% < |variance| <= 15%`: review required
  - `|variance| > 15%`: significant concern
- Vendor mapped category unit rate versus historical USD/Sqm: same ±5% / ±15% thresholds.

Unmapped priced rows and missing benchmarks are reported explicitly.

## Local validation

```bash
conda activate agentdev
pip install -e '.[dev,azure]'
pytest -q
ruff check budget_agent tests scripts
python -m budget_agent.server
```

The MCP endpoint is `http://localhost:8000/mcp`; health is `http://localhost:8000/healthz`.

## Teams app

```bash
cd teams_app
npm install
npm run build
```

Set the values in `teams_app/.env.example`, then run `npm start`. Upload an `.xlsx` file in Teams;
the bot calls `evaluate_budget_workbook` over MCP and keeps the returned report ID for follow-up
questions in the same conversation.

## Azure deployment

```bash
conda activate agentdev
export AZURE_SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
export AZURE_RESOURCE_GROUP="rg-budget-agent"
export AZURE_LOCATION="eastus2"
export ACA_SANDBOX_GROUP="aca-sbx-budget-agent"
export COPILOT_GITHUB_TOKEN="<GitHub token authorized for Copilot requests>"
python scripts/deploy_sandbox.py

export MCP_URL="$(python -c 'import json; print(json.load(open(".azure/sandbox-deployment.json"))["mcp_url"])')"
bash scripts/deploy_teams.sh
```

The scripts create an Azure Container Apps Sandbox MCP service and a single-tenant Teams bot,
enable the Microsoft Teams channel, and generate `.azure/engineering-budget-teams-app.zip` for
Teams upload. The `.azure/` directory and all deployment-specific identifiers are intentionally
excluded from source control.
