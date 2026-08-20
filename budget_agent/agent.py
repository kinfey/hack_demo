from __future__ import annotations

import json
import os
import re

from agent_framework.github import GitHubCopilotAgent, GitHubCopilotOptions
from copilot.generated.rpc import PermissionDecisionReject

from budget_agent.documents import DocumentChunk
from budget_agent.models import BudgetEvaluation, StructuredBudgetInput

MODEL = os.getenv("GITHUB_COPILOT_MODEL", "gpt-5.6-sol")

INSTRUCTIONS = """
You are a senior quantity-surveying and engineering-budget review agent.
Use only the supplied deterministic evaluation JSON. Never invent prices, categories, or mappings.
All unit rates are USD per Sqm. Explain:
1. Page 1: vendor total price versus PER Budget using ±10% approval and ±20% conditional thresholds;
2. Page 2: mapped vendor category price versus QS Estimate using ±5% reasonable and ±15% review thresholds;
3. Page 3: mapped vendor unit rate versus historical unit rate using the same ±5% and ±15% thresholds.
4. Page 4: QS requirements versus Vendor Quotation for construction scope, specification, brand, and
   quantity/unit. Prioritize red mismatches, yellow clarifications, and gray missing information.
Use the report traffic lights consistently: green means approve/reasonable, yellow means conditional/review,
red means reject/significant concern, and gray means benchmark missing.
Call out missing benchmarks and unmapped items explicitly. Recommend the commercially strongest vendor,
but identify category-level risks and negotiation targets. Respond in the user's language.
""".strip()

DOCUMENT_QA_INSTRUCTIONS = """
You answer questions about engineering-budget source files using retrieval-augmented generation.
Use only the supplied evaluation JSON and retrieved source excerpts. Never invent a value or claim that
is not supported by that evidence. Cite factual statements inline with [filename#chunk] references.
If the retrieved evidence is insufficient, say which information is missing instead of guessing.

When the question requires arithmetic, use the exact evidence values and:
1. state the input values and units;
2. show the formula;
3. calculate the result;
4. preserve the requested currency/unit and use sensible rounding.
Prefer deterministic evaluation JSON values over OCR/extracted text when both represent the same metric.
Distinguish percentages from decimal ratios and USD totals from USD/Sqm unit rates. Respond in the user's
language. For questions about scope, specification, brand, quantity, or unit, use scope_comparisons first,
then use retrieved excerpts for supporting detail. Explain the commercial/technical risk and give a concrete
clarification, compliance, substitution, or negotiation recommendation.
""".strip()

EXTRACTION_INSTRUCTIONS = """
You extract engineering-budget source documents into one strict JSON object.
Use only supplied content and preserve every monetary value exactly. Do not calculate evaluation results.
Return raw JSON only, with this schema:
{
  "project_name": "string",
  "construction_area_sqm": number,
  "per_budget": {"category": amount_usd},
  "qs_estimate": {"category": amount_usd},
  "historical_unit_rates": {"category": unit_rate_usd_per_sqm},
  "mappings": {"vendor_line_description": "benchmark_category"},
  "qs_rows": [{
    "description": "line item used to align with vendor quotation",
    "construction_scope": "string or empty",
    "specification": "string or empty",
    "brand": "string or empty",
    "quantity": number or null,
    "unit": "string or empty"
  }],
  "vendor_rows": [{
    "description": "string",
    "amounts_usd": {"vendor name": amount_usd},
    "vendor": "vendor name when this row belongs to one vendor, otherwise null",
    "construction_scope": "string or empty",
    "specification": "string or empty",
    "brand": "string or empty",
    "quantity": number or null,
    "unit": "string or empty"
  }],
  "vendor_quoted_totals": {"vendor name": amount_usd}
}
Convert construction area from Sqft to Sqm only when Sqm is unavailable, using 1 Sqft = 0.09290304 Sqm.
Historical values must be category unit rates, not a grand total. Exclude total rows from category
dictionaries and vendor_rows. Keep category names aligned with the mapping targets. If a required value is
absent, do not invent it; use an empty object/list or zero so validation can report the problem.

Extract the four technical/commercial comparison fields from both QS Estimation and Vendor Quotation:
construction scope, specification, brand, and quantity/unit. Preserve model numbers, dimensions, materials,
standards, exclusions, "or equivalent" wording, and quantity units verbatim. Put QS line-level requirements
in qs_rows. Populate the corresponding fields on every vendor_rows item. If vendor documents use one sheet
per vendor, set vendor to that sheet/vendor name. Do not collapse different vendor specifications or brands
into one shared row.

Documents may use arbitrary filenames, worksheet names, page layouts, header rows, column positions, merged
cells, bilingual labels, or one worksheet per vendor. Identify data by semantic headers and row structure,
not fixed locations. A vendor may be named in a worksheet title or in a cell above the quotation table.
Ignore blank rows, section headings without amounts, subtotals, formulas without cached values, and repeated
page headers.

When the same source category appears in multiple documents, prefer the dedicated source document whose
filename/content most specifically describes that category. Treat a combined "General Version", template,
or example workbook as fallback/reference data for a category only when no dedicated source document supplies
that category. Never add conflicting versions together. Project name and construction area may be taken from
the vendor quotation or general information document when they are absent from a dedicated summary.
""".strip()


def deny_permission(_request: object, _invocation: dict[str, str]) -> PermissionDecisionReject:
    return PermissionDecisionReject(feedback="This read-only budget agent does not grant external actions.")


def _parse_json_response(value: str) -> dict:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    return json.loads(text)


async def extract_structured_budget(documents: list[dict[str, str]]) -> StructuredBudgetInput:
    agent = GitHubCopilotAgent(
        instructions=EXTRACTION_INSTRUCTIONS,
        name="EngineeringBudgetDocumentExtractor",
        description="Normalizes PDF, Word, and Excel engineering-budget sources.",
        default_options=GitHubCopilotOptions(
            model=MODEL,
            timeout=float(os.getenv("GITHUB_COPILOT_TIMEOUT", "180")),
            on_permission_request=deny_permission,
        ),
    )
    manifest = [
        {
            "filename": document["filename"],
            "recognized_sources": document["recognized_sources"],
        }
        for document in documents
    ]
    prompt = (
        "Source manifest (dedicated files take precedence over combined/general files):\n"
        f"{json.dumps(manifest, ensure_ascii=False)}\n"
        "Extract and merge these source documents:\n"
        f"{json.dumps(documents, ensure_ascii=False)}"
    )
    async with agent:
        result = await agent.run(prompt)
    try:
        return StructuredBudgetInput.model_validate(_parse_json_response(str(result)))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Document extraction did not return valid structured budget data: {exc}") from exc


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
    evidence: list[DocumentChunk] | None = None,
) -> str:
    agent = GitHubCopilotAgent(
        instructions=DOCUMENT_QA_INSTRUCTIONS if evidence else INSTRUCTIONS,
        name="EngineeringBudgetRagAgent" if evidence else "EngineeringBudgetAgent",
        default_options=GitHubCopilotOptions(
            model=MODEL,
            timeout=float(os.getenv("GITHUB_COPILOT_TIMEOUT", "180")),
            on_permission_request=deny_permission,
        ),
    )
    prompt_parts = [
        f"Output language: {language}.",
        f"Question: {question}",
        f"Evaluation JSON: {report.model_dump_json(exclude={'executive_summary'})}",
    ]
    if evidence:
        prompt_parts.append(
            "Retrieved source excerpts:\n"
            + "\n\n".join(
                f"[{chunk['chunk_id']}]\n{chunk['content']}"
                for chunk in evidence
            )
        )
    prompt = "\n".join(prompt_parts)
    async with agent:
        result = await agent.run(prompt)
    return str(result)
