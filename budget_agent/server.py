from __future__ import annotations

import base64
import os
from collections import OrderedDict

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from budget_agent.agent import answer_report_question, create_executive_summary
from budget_agent.evaluator import WorkbookValidationError, evaluate_workbook
from budget_agent.models import BudgetEvaluation

REPORT_LIMIT = int(os.getenv("REPORT_CACHE_SIZE", "100"))
reports: OrderedDict[str, BudgetEvaluation] = OrderedDict()

mcp = FastMCP(
    name="Engineering Budget Evaluation MCP",
    instructions=(
        "Evaluate uploaded engineering budget Excel workbooks. "
        "Vendor rows are mapped strictly through MAPPING RULES and all unit rates use Sqm."
    ),
    host="0.0.0.0",
    port=int(os.getenv("PORT", "8000")),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def _store(report: BudgetEvaluation) -> None:
    reports[report.report_id] = report
    reports.move_to_end(report.report_id)
    while len(reports) > REPORT_LIMIT:
        reports.popitem(last=False)


@mcp.tool()
async def evaluate_budget_workbook(
    filename: str,
    file_base64: str,
    include_ai_summary: bool = True,
    language: str = "zh-CN",
) -> dict:
    """Evaluate an Excel budget workbook and return structured vendor recommendations."""
    try:
        content = base64.b64decode(file_base64, validate=True)
    except ValueError as exc:
        raise ValueError("file_base64 is not valid Base64.") from exc
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Only .xlsx workbooks are supported.")
    try:
        report = evaluate_workbook(content, filename)
    except WorkbookValidationError:
        raise
    if include_ai_summary:
        report.executive_summary = await create_executive_summary(report, language)
    _store(report)
    return report.model_dump()


@mcp.tool()
async def ask_budget_report(
    report_id: str,
    question: str,
    language: str = "zh-CN",
) -> dict:
    """Ask a follow-up question about a previously evaluated workbook."""
    report = reports.get(report_id)
    if report is None:
        raise ValueError("Report not found in this service instance. Upload and evaluate the workbook again.")
    answer = await answer_report_question(report, question, language)
    return {"report_id": report_id, "answer": answer}


@mcp.tool()
def get_budget_report(report_id: str) -> dict:
    """Return a cached structured budget report without invoking the model."""
    report = reports.get(report_id)
    if report is None:
        raise ValueError("Report not found.")
    return report.model_dump()


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "engineering-budget-agent",
            "model": os.getenv("GITHUB_COPILOT_MODEL", "gpt-5.6-sol"),
            "mcp": "/mcp",
        }
    )


app = mcp.streamable_http_app()
app.routes.insert(0, Route("/healthz", health, methods=["GET"]))


def main() -> None:
    uvicorn.run(
        "budget_agent.server:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
