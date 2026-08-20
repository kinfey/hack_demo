from pathlib import Path

import pytest

from budget_agent.evaluator import evaluate_structured_input, evaluate_workbook
from budget_agent.models import QSRequirementRow, StructuredBudgetInput, VendorQuoteRow

SAMPLE = Path("data/General Version.xlsx")


def test_sample_workbook_matches_summary_baseline() -> None:
    report = evaluate_workbook(SAMPLE.read_bytes(), SAMPLE.name)

    assert report.construction_area_sqm == pytest.approx(3563)
    assert report.per_budget_total_usd == pytest.approx(10087575.23)
    assert report.qs_total_usd == pytest.approx(10614202.80268297)
    assert report.historical_weighted_unit_rate_usd_sqm == pytest.approx(2500)
    assert [vendor.total_amount_usd for vendor in report.vendors] == pytest.approx(
        [
            10922445.73244121,
            11193180.874870673,
            10177153.292950075,
            11261478.954073869,
            11627647.159004072,
        ]
    )
    assert [vendor.unit_rate_usd_sqm for vendor in report.vendors] == pytest.approx(
        [
            3065.5194309405583,
            3141.5045958099,
            2856.3438936149523,
            3160.6732961195253,
            3263.442929835552,
        ]
    )
    assert report.unmatched_vendor_items == []


def test_per_budget_decisions_follow_output_thresholds() -> None:
    report = evaluate_workbook(SAMPLE.read_bytes(), SAMPLE.name)
    decisions = {vendor.vendor: vendor.per_budget_decision for vendor in report.vendors}
    assert decisions == {
        "Vendor A": "approve",
        "Vendor B": "conditional_approval",
        "Vendor C": "approve",
        "Vendor D": "conditional_approval",
        "Vendor E": "conditional_approval",
    }
    colors = {vendor.vendor: vendor.per_budget_status_color for vendor in report.vendors}
    assert colors == {
        "Vendor A": "green",
        "Vendor B": "yellow",
        "Vendor C": "green",
        "Vendor D": "yellow",
        "Vendor E": "yellow",
    }


def test_output_comparisons_include_traffic_light_statuses() -> None:
    report = evaluate_workbook(SAMPLE.read_bytes(), SAMPLE.name)
    decision_colors = {
        "reasonable": "green",
        "review_required": "yellow",
        "significant_concern": "red",
        "benchmark_missing": "gray",
    }
    qs_colors: set[str] = set()
    historical_colors: set[str] = set()

    for vendor in report.vendors:
        for comparison in vendor.qs_comparisons:
            assert comparison.status_color == decision_colors[comparison.decision]
            qs_colors.add(comparison.status_color)
        for comparison in vendor.historical_comparisons:
            assert comparison.status_color == decision_colors[comparison.decision]
            historical_colors.add(comparison.status_color)

    assert qs_colors == {"green", "yellow", "red", "gray"}
    assert historical_colors == {"green", "yellow", "red", "gray"}


def test_qs_vendor_scope_comparison_flags_brand_and_quantity_differences() -> None:
    data = StructuredBudgetInput(
        project_name="Scope comparison",
        construction_area_sqm=1000,
        per_budget={"Electrical": 100000},
        qs_estimate={"Electrical": 100000},
        historical_unit_rates={"Electrical": 100},
        mappings={"Lighting installation": "Electrical"},
        qs_rows=[
            QSRequirementRow(
                description="Electrical",
                construction_scope="Supply and install light fixtures",
                specification="LED 4000K, IP44",
                brand="Philips",
                quantity=100,
                unit="sets",
            )
        ],
        vendor_rows=[
            VendorQuoteRow(
                description="Lighting installation",
                vendor="Vendor A",
                amounts_usd={"Vendor A": 110000},
                construction_scope="Supply and install light fixtures",
                specification="LED 4000K, IP44",
                brand="Generic",
                quantity=80,
                unit="sets",
            )
        ],
    )

    report = evaluate_structured_input(data, "sources", b"scope-comparison")
    comparison = report.scope_comparisons[0]

    assert comparison.construction_scope.status == "match"
    assert comparison.specification.status == "match"
    assert comparison.brand.status == "mismatch"
    assert comparison.quantity_unit.status == "mismatch"
    assert comparison.overall_status == "red"
    assert "brand" in comparison.recommendation
    assert "quantity/unit" in comparison.recommendation
