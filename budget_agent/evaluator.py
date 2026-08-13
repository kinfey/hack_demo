from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from budget_agent.models import BudgetEvaluation, Comparison, Decision, VendorAssessment

REQUIRED_SHEETS = {
    "Summary",
    "PER Budget",
    "QS Estimation",
    "Vendor Quotation",
    "MAPPING RULES",
    "Historical Unit Rates",
}


class WorkbookValidationError(ValueError):
    pass


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _key(value: Any) -> str:
    return _text(value).casefold()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _find_label_number(ws: Worksheet, label: str) -> float | None:
    target = _key(label)
    for row in ws.iter_rows():
        for cell in row:
            if target in _key(cell.value):
                for candidate in row[cell.column :]:
                    number = _number(candidate.value)
                    if number is not None:
                        return number
    return None


def _two_column_table(ws: Worksheet, *, total_prefixes: tuple[str, ...]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in ws.iter_rows(values_only=True):
        name = _text(row[0] if row else None)
        amount = _number(row[1] if len(row) > 1 else None)
        if not name or amount is None or _key(name).startswith(total_prefixes):
            continue
        result[name] = amount
    return result


def _mapping_table(ws: Worksheet) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in ws.iter_rows(values_only=True):
        source = _text(row[0] if row else None)
        target = _text(row[1] if len(row) > 1 else None)
        if source and target and "vendor wbs" not in _key(source):
            result[_key(source)] = target
    return result


def _decision(variance: float, reasonable: float, review: float) -> Decision:
    absolute = abs(variance)
    if absolute <= reasonable:
        return "reasonable"
    if absolute <= review:
        return "review_required"
    return "significant_concern"


def _total_decision(variance: float) -> Decision:
    absolute = abs(variance)
    if absolute <= 0.10:
        return "approve"
    if absolute <= 0.20:
        return "conditional_approval"
    return "reject"


def _vendor_table(
    ws: Worksheet,
    mappings: dict[str, str],
) -> tuple[dict[str, dict[str, float]], dict[str, float], list[str]]:
    header_row = None
    vendor_columns: dict[int, str] = {}
    description_column = None
    for row in ws.iter_rows():
        labels = [_text(cell.value) for cell in row]
        if any(label.casefold().startswith("vendor-") for label in labels):
            header_row = row[0].row
            vendor_columns = {
                cell.column: _text(cell.value).replace("Vendor-", "Vendor ")
                for cell in row
                if _key(cell.value).startswith("vendor-")
            }
        if any("description" in label.casefold() for label in labels):
            description_column = next(
                cell.column for cell in row if "description" in _key(cell.value)
            )
        if header_row and description_column:
            break
    if not header_row or not vendor_columns or not description_column:
        raise WorkbookValidationError("Vendor Quotation headers could not be identified.")

    category_totals: dict[str, dict[str, float]] = {
        vendor: defaultdict(float) for vendor in vendor_columns.values()
    }
    quoted_totals: dict[str, float] = defaultdict(float)
    unmatched: list[str] = []
    for row_index in range(header_row + 1, ws.max_row + 1):
        description = _text(ws.cell(row_index, description_column).value)
        if not description:
            continue
        values = {
            vendor: _number(ws.cell(row_index, column).value)
            for column, vendor in vendor_columns.items()
        }
        if _key(description) == "total":
            quoted_totals.update({vendor: amount or 0.0 for vendor, amount in values.items()})
            continue
        if not any(amount not in (None, 0.0) for amount in values.values()):
            continue
        category = mappings.get(_key(description))
        if not category:
            unmatched.append(description)
            continue
        for vendor, amount in values.items():
            if amount is not None:
                category_totals[vendor][category] += amount

    for vendor, categories in category_totals.items():
        calculated = sum(categories.values())
        quoted = quoted_totals.get(vendor)
        if quoted and abs(calculated - quoted) > 0.01:
            raise WorkbookValidationError(
                f"{vendor} mapped category total {calculated:.2f} does not match quoted total {quoted:.2f}."
            )
        quoted_totals[vendor] = quoted or calculated
    return category_totals, quoted_totals, sorted(set(unmatched))


def evaluate_workbook(content: bytes, filename: str) -> BudgetEvaluation:
    try:
        workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise WorkbookValidationError(f"Unable to open Excel workbook: {exc}") from exc

    missing = sorted(REQUIRED_SHEETS.difference(workbook.sheetnames))
    if missing:
        raise WorkbookValidationError(f"Missing required tabs: {', '.join(missing)}")

    summary = workbook["Summary"]
    area = _find_label_number(summary, "Construction Area (Sqm)")
    if not area or area <= 0:
        sqft = _find_label_number(summary, "Construction Area (Sqft)")
        area = sqft * 0.09290304 if sqft else None
    if not area or area <= 0:
        raise WorkbookValidationError("Construction area in Sqm is missing or invalid.")

    per_budget = _two_column_table(workbook["PER Budget"], total_prefixes=("total",))
    qs_estimate = _two_column_table(workbook["QS Estimation"], total_prefixes=("total",))
    historical = _two_column_table(
        workbook["Historical Unit Rates"], total_prefixes=("weighted average",)
    )
    mappings = _mapping_table(workbook["MAPPING RULES"])
    if not per_budget or not qs_estimate or not historical or not mappings:
        raise WorkbookValidationError("One or more budget benchmark tabs contain no usable data.")

    vendor_categories, vendor_totals, unmatched = _vendor_table(
        workbook["Vendor Quotation"], mappings
    )
    per_total = sum(per_budget.values())
    qs_total = sum(qs_estimate.values())
    historical_weighted = sum(historical.values())
    warnings: list[str] = []
    if unmatched:
        warnings.append(
            f"{len(unmatched)} priced Vendor Quotation item(s) were not mapped by MAPPING RULES."
        )

    vendors: list[VendorAssessment] = []
    for vendor, categories in vendor_categories.items():
        total = vendor_totals[vendor]
        total_variance = total / per_total - 1 if per_total else 0.0
        qs_comparisons: list[Comparison] = []
        historical_comparisons: list[Comparison] = []
        for category, amount in sorted(categories.items()):
            unit_rate = amount / area
            qs_amount = qs_estimate.get(category)
            if qs_amount is None or qs_amount == 0:
                qs_comparisons.append(
                    Comparison(
                        category=category,
                        vendor_amount_usd=amount,
                        vendor_unit_rate_usd_sqm=unit_rate,
                        decision="benchmark_missing",
                    )
                )
            else:
                variance = amount / qs_amount - 1
                qs_comparisons.append(
                    Comparison(
                        category=category,
                        vendor_amount_usd=amount,
                        vendor_unit_rate_usd_sqm=unit_rate,
                        benchmark_amount_usd=qs_amount,
                        benchmark_unit_rate_usd_sqm=qs_amount / area,
                        variance_pct=variance,
                        decision=_decision(variance, 0.05, 0.15),
                    )
                )

            historical_rate = historical.get(category)
            if historical_rate is None or historical_rate == 0:
                historical_comparisons.append(
                    Comparison(
                        category=category,
                        vendor_amount_usd=amount,
                        vendor_unit_rate_usd_sqm=unit_rate,
                        decision="benchmark_missing",
                    )
                )
            else:
                variance = unit_rate / historical_rate - 1
                historical_comparisons.append(
                    Comparison(
                        category=category,
                        vendor_amount_usd=amount,
                        vendor_unit_rate_usd_sqm=unit_rate,
                        benchmark_unit_rate_usd_sqm=historical_rate,
                        variance_pct=variance,
                        decision=_decision(variance, 0.05, 0.15),
                    )
                )

        vendors.append(
            VendorAssessment(
                vendor=vendor,
                total_amount_usd=total,
                unit_rate_usd_sqm=total / area,
                per_budget_variance_pct=total_variance,
                per_budget_decision=_total_decision(total_variance),
                recommended_value_usd=min(total, per_total),
                potential_savings_usd=max(total - per_total, 0.0),
                qs_comparisons=qs_comparisons,
                historical_comparisons=historical_comparisons,
            )
        )

    project_name = _text(workbook["Cover"]["A1"].value) or Path(filename).stem
    report_id = hashlib.sha256(content).hexdigest()[:16]
    return BudgetEvaluation(
        report_id=report_id,
        project_name=project_name,
        source_filename=Path(filename).name,
        construction_area_sqm=area,
        per_budget_total_usd=per_total,
        per_budget_unit_rate_usd_sqm=per_total / area,
        qs_total_usd=qs_total,
        qs_unit_rate_usd_sqm=qs_total / area,
        historical_weighted_unit_rate_usd_sqm=historical_weighted,
        vendors=vendors,
        unmatched_vendor_items=unmatched,
        warnings=warnings,
    )
