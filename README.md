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

### Application flow

**Microsoft Teams user**
→ uploads PDF, Word, or Excel sources
→ **Teams bot**
→ validates source coverage through the **MCP client**
→ requests any missing PER, QS, quotation, mapping, history, or summary source
→ calls the **Budget Evaluation MCP service**
→ runs deterministic comparison and model-assisted document normalization
→ returns a structured four-page report and executive recommendation
→ renders **Teams Adaptive Cards**
→ supports report-scoped follow-up Q&A and approval.

| Stage | Component | Responsibility | State |
|---|---|---|---|
| 1 | Microsoft Teams | File upload, chat questions, and approval actions | Teams conversation |
| 2 | Teams bot (`teams_app/src/teamsBot.ts`) | Accumulates attachments, tracks report IDs, routes follow-up questions, and replaces approved cards with a completed state | Bounded in-memory conversation and approval maps |
| 3 | Adaptive Card layer (`teams_app/src/cards.ts`) | Upload guidance, four-page evaluation dashboard, errors, and idempotent approval completion UI | Card payload |
| 4 | MCP client (`teams_app/src/mcpClient.ts`) | Calls inspection, evaluation, and report Q&A tools over Streamable HTTP | Request scoped |
| 5 | MCP server (`budget_agent/server.py`) | Exposes `/mcp`, validates source completeness, coordinates evaluation, and caches reports and document chunks | Bounded in-memory report cache |
| 6 | Document pipeline (`budget_agent/documents.py`) | Decodes PDF, Word, and Excel files, identifies source types, chunks content, and retrieves report evidence | Report scoped |
| 7 | Evaluation engine (`budget_agent/evaluator.py`) | Maps vendor WBS rows, normalizes USD/Sqm, calculates variances, and assigns traffic-light decisions | Deterministic structured model |
| 8 | AI layer (`budget_agent/agent.py`) | Uses GitHub Copilot `gpt-5.6-sol` to normalize non-workbook inputs, generate the executive narrative, and answer grounded questions | Ephemeral agent session |

### Azure deployment topology

| Azure resource | Deployed workload | Connection |
|---|---|---|
| Microsoft Entra ID application | Single-tenant bot identity and credential | Authenticates Azure Bot Service requests to the Teams bot |
| Azure Bot Service + Teams channel | Teams registration and messaging endpoint | Sends activities to `https://<teams-container-app>/api/messages` |
| Azure Container App | Node.js 20 Teams bot image | Pulls from ACR and calls the MCP endpoint through `MCP_URL` |
| Azure Container Registry | Versioned `engineering-budget-teams:<timestamp>` images | Supplies immutable Teams bot revisions |
| Azure Container Apps Sandbox | Python 3.12 Budget Evaluation MCP service | Exposes anonymous HTTPS Streamable HTTP at `/mcp` |
| GitHub Copilot SDK | `gpt-5.6-sol` model access inside the Sandbox | Receives normalized document content or deterministic report JSON |

**Runtime request path**
→ Teams channel
→ Azure Bot Service
→ Teams Container App `/api/messages`
→ Sandbox MCP `/mcp`
→ document and evaluation pipeline
→ GitHub Copilot model when extraction, summary, or grounded Q&A is required
→ Adaptive Card or chat response returned through the same path.

**Approval path**
→ user selects **Approve** on an Adaptive Card
→ Teams sends an Adaptive Card invoke or submit activity
→ the bot derives a stable conversation/action key
→ duplicate approvals return the existing result
→ the original card is replaced with approver, timestamp, and completed status.

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
