import base64
from pathlib import Path

import pytest

from budget_agent.documents import (
    chunk_documents,
    extract_document_text,
    identify_sources,
    prepare_documents,
    retrieve_document_chunks,
    source_status,
)
from budget_agent.models import UploadedDocument

DATA = Path("data")


@pytest.mark.parametrize(
    ("filename", "expected", "unexpected"),
    [
        ("PER-Budget0814.pdf", {"per_budget", "project_summary"}, set()),
        ("QS Estimation0814.pdf", {"qs_estimate", "project_summary"}, set()),
        ("Vendor Quotation0814.xlsx", {"vendor_quotation", "project_summary"}, set()),
        ("Mapping Rules0814.docx", {"mapping_rules"}, {"per_budget", "qs_estimate"}),
        ("History.xlsx", {"historical_rates"}, set()),
    ],
)
def test_data_samples_are_classified_by_structure(
    filename: str,
    expected: set[str],
    unexpected: set[str],
) -> None:
    path = DATA / filename
    text = extract_document_text(filename, path.read_bytes())
    sources = identify_sources(filename, text)

    assert expected <= sources
    assert not unexpected.intersection(sources)


def test_split_data_samples_satisfy_all_required_sources() -> None:
    filenames = [
        "PER-Budget0814.pdf",
        "QS Estimation0814.pdf",
        "Vendor Quotation0814.xlsx",
        "Mapping Rules0814.docx",
        "History.xlsx",
    ]
    documents = [
        UploadedDocument(
            filename=filename,
            file_base64=base64.b64encode((DATA / filename).read_bytes()).decode(),
        )
        for filename in filenames
    ]

    extracted, recognized, _ = prepare_documents(documents)
    status = source_status(recognized)

    assert status["complete"]
    assert len(extracted) == len(filenames)


def test_retrieval_can_scope_questions_to_one_file() -> None:
    chunks = chunk_documents(
        [
            {
                "filename": "PER Budget.pdf",
                "content": "### PAGE 1\nConstruction budget total USD 1,000,000",
            },
            {
                "filename": "Vendor Quote.xlsx",
                "content": "### SHEET: Quote\nElectrical works\tUSD 125,000",
            },
        ],
        max_chars=80,
    )

    matches = retrieve_document_chunks(
        chunks,
        "What is the electrical works amount?",
        filename="Vendor Quote.xlsx",
    )

    assert matches
    assert {match["filename"] for match in matches} == {"Vendor Quote.xlsx"}
    assert "125,000" in matches[0]["content"]


def test_retrieval_rejects_unknown_report_file() -> None:
    chunks = chunk_documents([{"filename": "Known.pdf", "content": "Budget total 100"}])

    with pytest.raises(ValueError, match="Document not found"):
        retrieve_document_chunks(chunks, "total", filename="Missing.pdf")
