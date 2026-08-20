from __future__ import annotations

import base64
import os
from collections import OrderedDict

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from budget_agent.agent import answer_report_question, create_executive_summary, extract_structured_budget
from budget_agent.documents import (
    DocumentChunk,
    DocumentValidationError,
    chunk_documents,
    decode_document,
    prepare_documents,
    retrieve_document_chunks,
    source_status,
)
from budget_agent.evaluator import (
    WorkbookValidationError,
    evaluate_structured_input,
    evaluate_workbook,
)
from budget_agent.models import BudgetEvaluation, UploadedDocument

REPORT_LIMIT = int(os.getenv("REPORT_CACHE_SIZE", "100"))
reports: OrderedDict[str, BudgetEvaluation] = OrderedDict()
report_documents: dict[str, list[DocumentChunk]] = {}

mcp = FastMCP(
    name="Engineering Budget Evaluation MCP",
    instructions=(
        "Evaluate engineering budget sources uploaded as PDF, Word, or Excel documents. "
        "Vendor rows are mapped strictly through Mapping Rules and all unit rates use Sqm."
    ),
    host="0.0.0.0",
    port=int(os.getenv("PORT", "8000")),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def _store(report: BudgetEvaluation, documents: list[DocumentChunk] | None = None) -> None:
    reports[report.report_id] = report
    if documents is not None:
        report_documents[report.report_id] = documents
    reports.move_to_end(report.report_id)
    while len(reports) > REPORT_LIMIT:
        expired_report_id, _ = reports.popitem(last=False)
        report_documents.pop(expired_report_id, None)


def _report_payload(report: BudgetEvaluation) -> dict:
    payload = report.model_dump()
    payload["document_names"] = list(
        dict.fromkeys(chunk["filename"] for chunk in report_documents.get(report.report_id, []))
    )
    return payload


@mcp.tool()
async def evaluate_budget_workbook(
    filename: str,
    file_base64: str,
    include_ai_summary: bool = True,
    language: str = "en-US",
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
    extracted, _, _ = prepare_documents(
        [UploadedDocument(filename=filename, file_base64=file_base64)]
    )
    _store(report, chunk_documents(extracted))
    return _report_payload(report)


@mcp.tool()
def inspect_budget_documents(documents: list[UploadedDocument]) -> dict:
    """Identify uploaded budget sources and list anything still required before evaluation."""
    _, recognized, _ = prepare_documents(documents)
    return source_status(recognized)


@mcp.tool()
async def evaluate_budget_documents(
    documents: list[UploadedDocument],
    include_ai_summary: bool = True,
    language: str = "en-US",
) -> dict:
    """Evaluate complete budget sources uploaded as PDF, Word, or Excel documents."""
    extracted, recognized, digest = prepare_documents(documents)
    status = source_status(recognized)
    if not status["complete"]:
        missing = ", ".join(item["name"] for item in status["missing_sources"])
        raise DocumentValidationError(f"Additional source files are required: {missing}.")

    report: BudgetEvaluation
    if len(documents) == 1 and documents[0].filename.casefold().endswith(".xlsx"):
        filename, content = decode_document(documents[0])
        try:
            report = evaluate_workbook(content, filename)
        except WorkbookValidationError:
            structured = await extract_structured_budget(extracted)
            report = evaluate_structured_input(structured, filename, digest)
    else:
        structured = await extract_structured_budget(extracted)
        filenames = ", ".join(document.filename for document in documents)
        report = evaluate_structured_input(structured, filenames, digest)

    if include_ai_summary:
        report.executive_summary = await create_executive_summary(report, language)
    _store(report, chunk_documents(extracted))
    return _report_payload(report)


@mcp.tool()
async def ask_budget_report(
    report_id: str,
    question: str,
    language: str = "en-US",
    filename: str | None = None,
) -> dict:
    """Ask a grounded follow-up question across all source files or within one named file."""
    report = reports.get(report_id)
    if report is None:
        raise ValueError("Report not found in this service instance. Upload and evaluate the workbook again.")
    evidence = retrieve_document_chunks(
        report_documents.get(report_id, []),
        question,
        filename=filename,
    )
    answer = await answer_report_question(report, question, language, evidence)
    return {
        "report_id": report_id,
        "answer": answer,
        "sources": [
            {"filename": chunk["filename"], "chunk_id": chunk["chunk_id"]}
            for chunk in evidence
        ],
    }


@mcp.tool()
def list_budget_report_documents(report_id: str) -> dict:
    """List source documents available for report-scoped RAG questions."""
    if report_id not in reports:
        raise ValueError("Report not found.")
    return {
        "report_id": report_id,
        "documents": list(
            dict.fromkeys(chunk["filename"] for chunk in report_documents.get(report_id, []))
        ),
    }


@mcp.tool()
def get_budget_report(report_id: str) -> dict:
    """Return a cached structured budget report without invoking the model."""
    report = reports.get(report_id)
    if report is None:
        raise ValueError("Report not found.")
    return _report_payload(report)


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
