from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Decision = Literal[
    "approve",
    "conditional_approval",
    "reject",
    "reasonable",
    "review_required",
    "significant_concern",
    "benchmark_missing",
]
TrafficLight = Literal["green", "yellow", "red", "gray"]


class Comparison(BaseModel):
    category: str
    vendor_amount_usd: float
    vendor_unit_rate_usd_sqm: float
    benchmark_amount_usd: float | None = None
    benchmark_unit_rate_usd_sqm: float | None = None
    variance_pct: float | None = None
    decision: Decision
    status_color: TrafficLight


class VendorAssessment(BaseModel):
    vendor: str
    total_amount_usd: float
    unit_rate_usd_sqm: float
    per_budget_variance_pct: float
    per_budget_decision: Decision
    per_budget_status_color: TrafficLight
    recommended_value_usd: float
    potential_savings_usd: float
    qs_comparisons: list[Comparison]
    historical_comparisons: list[Comparison]


class BudgetEvaluation(BaseModel):
    report_id: str
    project_name: str
    source_filename: str
    construction_area_sqm: float
    per_budget_total_usd: float
    per_budget_unit_rate_usd_sqm: float
    qs_total_usd: float
    qs_unit_rate_usd_sqm: float
    historical_weighted_unit_rate_usd_sqm: float
    vendors: list[VendorAssessment]
    unmatched_vendor_items: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    executive_summary: str | None = None
