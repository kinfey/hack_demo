# Engineering Budget Evaluation Agent

Microsoft Agent Framework + GitHub Copilot SDK (`gpt-5.6-sol`) solution for evaluating engineering
budget source documents through MCP and Microsoft Teams.

Users may upload one combined file or several files over multiple messages in PDF, DOC/DOCX, or
XLS/XLSX format. The app checks for `PER Budget`, `QS Estimation`, `Vendor Quotation`, `MAPPING
RULES`, `Historical Unit Rates`, and `Summary`, then prompts for any missing source. The calculation
layer maps every priced vendor WBS row and normalizes category and total rates to USD/Sqm. GPT-5.6
Sol normalizes non-workbook documents, produces the English executive narrative, and answers
follow-up questions with report-scoped RAG over the uploaded source files.

## Architecture

```text
┌───────────────────────────────┐
│  User / Microsoft Teams      │
│  Uploads PDF/Word/Excel       │
│  budget source documents      │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│  Teams App                    │
│  - Accumulates attachments    │
│  - Prompts for missing input  │
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
│  - Validates source coverage  │
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

## OUTPUT-style dashboard

The MCP report and Teams Adaptive Card follow the workbook `OUTPUT` tab:

- Page 1 — Vendor total versus PER Budget
- Page 2 — Vendor mapped category amount versus QS Estimate
- Page 3 — Vendor mapped category USD/Sqm versus Historical Unit Rate
- Page 4 — QS versus Vendor construction scope, specification, brand, and quantity/unit

Traffic-light indicators are consistent across the structured JSON and Teams UI:

- 🟢 Green — approve / reasonable
- 🟡 Yellow — conditional approval / review required
- 🔴 Red — reject / significant cost concern
- ⚪ Gray — benchmark missing

Page 4 aligns each vendor line with the closest QS requirement. Text fields are normalized and compared
for compliance; quantity differences within ±5% match, ±5–15% require review, and differences above ±15%
or inconsistent units are flagged as mismatches. The result includes the QS value, vendor value, field-level
status, and a recommendation for clarification, compliance confirmation, substitution review, or repricing.

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

Set the values in `teams_app/.env.example`, then run `npm start`. Upload PDF, DOC/DOCX, or XLS/XLSX
files in Teams. The bot retains files within the conversation, shows which required source categories
are still missing, calls `evaluate_budget_documents` when all inputs are available, and keeps the
returned report ID for follow-up questions. A normal question retrieves evidence across all source
documents. Use `[filename] question` to chat with one file, and type `files` or `文件` to list the
available filenames. Questions may request totals, differences, percentages, unit-rate conversions,
and other calculations; answers include the evidence inputs, formula, result, unit, and source citations.

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
disable Sandbox auto-suspend, enable the Microsoft Teams channel, and generate
`.azure/engineering-budget-teams-app.zip` for Teams upload. The `.azure/` directory and all
deployment-specific identifiers are intentionally excluded from source control.
