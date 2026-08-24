import { Attachment, CardFactory } from "botbuilder";
import {
  BudgetReport,
  Comparison,
  ScopeComparison,
  SourceStatus,
  VendorAssessment,
} from "./mcpClient";

type TrafficLight = "green" | "yellow" | "red" | "gray";

export interface ApprovalResult {
  title: string;
  approvedBy: string;
  approvedAt: string;
}

const usd = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

const pct = (value: number | null) => value === null ? "N/A" : `${(value * 100).toFixed(1)}%`;

const icon = (status: TrafficLight) => ({
  green: "🟢",
  yellow: "🟡",
  red: "🔴",
  gray: "⚪",
})[status];

const color = (status: TrafficLight) => ({
  green: "Good",
  yellow: "Warning",
  red: "Attention",
  gray: "Default",
})[status];

const decision = (value: string) => ({
  approve: "Approve",
  conditional_approval: "Conditional approval",
  reject: "Reject",
  reasonable: "Reasonable",
  review_required: "Review required",
  significant_concern: "Significant cost concern",
  benchmark_missing: "Benchmark missing",
})[value] ?? value;

function statusCounts(comparisons: Comparison[]): string {
  const counts = { green: 0, yellow: 0, red: 0, gray: 0 };
  for (const item of comparisons) counts[item.status_color] += 1;
  return `🟢 ${counts.green}  🟡 ${counts.yellow}  🔴 ${counts.red}  ⚪ ${counts.gray}`;
}

function priorityComparisons(comparisons: Comparison[]): Comparison[] {
  const rank = { red: 0, yellow: 1, gray: 2, green: 3 };
  return [...comparisons]
    .filter((item) => item.status_color !== "green")
    .sort((left, right) =>
      rank[left.status_color] - rank[right.status_color]
      || Math.abs(right.variance_pct ?? 0) - Math.abs(left.variance_pct ?? 0)
    )
    .slice(0, 3);
}

function pageOneVendor(vendor: VendorAssessment) {
  const status = vendor.per_budget_status_color;
  return {
    type: "Container",
    separator: true,
    items: [
      {
        type: "TextBlock",
        text: `${icon(status)} ${vendor.vendor} — ${decision(vendor.per_budget_decision)}`,
        weight: "Bolder",
        color: color(status),
        wrap: true,
      },
      {
        type: "FactSet",
        facts: [
          { title: "Vendor total", value: usd(vendor.total_amount_usd) },
          { title: "Unit rate", value: `${usd(vendor.unit_rate_usd_sqm)}/Sqm` },
          { title: "Variance to PER", value: pct(vendor.per_budget_variance_pct) },
          { title: "Recommended value", value: usd(vendor.recommended_value_usd) },
          { title: "Potential savings", value: usd(vendor.potential_savings_usd) },
        ],
      },
    ],
  };
}

function comparisonPage(
  title: string,
  subtitle: string,
  vendors: VendorAssessment[],
  selector: (vendor: VendorAssessment) => Comparison[],
  unitRate: boolean,
) {
  const items: any[] = [
    { type: "TextBlock", text: title, weight: "Bolder", size: "Medium", color: "Accent" },
    { type: "TextBlock", text: subtitle, size: "Small", isSubtle: true, wrap: true },
  ];

  for (const vendor of vendors) {
    const comparisons = selector(vendor);
    items.push({
      type: "TextBlock",
      text: `${vendor.vendor}: ${statusCounts(comparisons)}`,
      weight: "Bolder",
      separator: true,
      wrap: true,
    });
    const rows = priorityComparisons(comparisons).map((item) => {
      const vendorValue = unitRate
        ? `${usd(item.vendor_unit_rate_usd_sqm)}/Sqm`
        : usd(item.vendor_amount_usd);
      const benchmark = unitRate
        ? item.benchmark_unit_rate_usd_sqm === null
          ? "N/A"
          : `${usd(item.benchmark_unit_rate_usd_sqm)}/Sqm`
        : item.benchmark_amount_usd === null
          ? "N/A"
          : usd(item.benchmark_amount_usd);
      return {
        type: "TableRow",
        cells: [
          tableCell(`${icon(item.status_color)} ${item.category}`, color(item.status_color)),
          tableCell(vendorValue),
          tableCell(benchmark),
          tableCell(pct(item.variance_pct)),
          tableCell(decision(item.decision), color(item.status_color)),
        ],
      };
    });
    items.push({
      type: "Table",
      firstRowAsHeaders: true,
      showGridLines: true,
      columns: [
        { width: 2 },
        { width: 1 },
        { width: 1 },
        { width: 1 },
        { width: 2 },
      ],
      rows: [
        {
          type: "TableRow",
          cells: [
            tableCell("Category", "Accent", true),
            tableCell(unitRate ? "Vendor USD/Sqm" : "Vendor amount", "Accent", true),
            tableCell(unitRate ? "Historical USD/Sqm" : "QS estimate", "Accent", true),
            tableCell("Variance", "Accent", true),
            tableCell("Decision", "Accent", true),
          ],
        },
        ...rows,
      ],
    });
  }

  return { type: "Container", separator: true, items };
}

function tableCell(text: string, textColor = "Default", bold = false) {
  return {
    type: "TableCell",
    items: [{
      type: "TextBlock",
      text,
      color: textColor,
      weight: bold ? "Bolder" : "Default",
      size: "Small",
      wrap: true,
    }],
  };
}

function scopeComparisonPage(comparisons: ScopeComparison[]) {
  const rank = { red: 0, yellow: 1, gray: 2, green: 3 };
  const priority = [...comparisons]
    .filter((item) => item.overall_status !== "green")
    .sort((left, right) => rank[left.overall_status] - rank[right.overall_status])
    .slice(0, 6);
  const fieldStatus = (item: ScopeComparison) => [
    `范围 ${icon(fieldColor(item.construction_scope.status))}`,
    `规格 ${icon(fieldColor(item.specification.status))}`,
    `品牌 ${icon(fieldColor(item.brand.status))}`,
    `数量/单位 ${icon(fieldColor(item.quantity_unit.status))}`,
  ].join("  ");
  const fieldDetail = (label: string, field: ScopeComparison["construction_scope"]) => ({
    type: "TextBlock",
    text: `${icon(fieldColor(field.status))} **${label}**  QS: ${field.expected}  |  Vendor: ${field.offered}`,
    size: "Small",
    wrap: true,
  });
  return {
    type: "Container",
    separator: true,
    items: [
      {
        type: "TextBlock",
        text: "Page 4 — QS vs Vendor Technical Scope",
        weight: "Bolder",
        size: "Medium",
        color: "Accent",
      },
      {
        type: "TextBlock",
        text: "逐项比较施工范围、规格、品牌、数量/单位。以下优先显示需要澄清或存在冲突的项目。",
        size: "Small",
        isSubtle: true,
        wrap: true,
      },
      ...(priority.length ? priority.map((item) => ({
        type: "Container",
        separator: true,
        items: [
          {
            type: "TextBlock",
            text: `${icon(item.overall_status)} ${item.vendor} — ${item.vendor_item}`,
            weight: "Bolder",
            color: color(item.overall_status),
            wrap: true,
          },
          { type: "TextBlock", text: fieldStatus(item), size: "Small", wrap: true },
          fieldDetail("施工范围", item.construction_scope),
          fieldDetail("规格", item.specification),
          fieldDetail("品牌", item.brand),
          fieldDetail("数量/单位", item.quantity_unit),
          { type: "TextBlock", text: item.recommendation, size: "Small", wrap: true },
        ],
      })) : [{
        type: "TextBlock",
        text: comparisons.length
          ? "四项要求均已对齐。"
          : "源文件未提供可结构化比较的四项明细；可通过 RAG 查询原文并要求澄清。",
        wrap: true,
      }]),
    ],
  };
}

function fieldColor(status: "match" | "review" | "mismatch" | "missing"): TrafficLight {
  return { match: "green", review: "yellow", mismatch: "red", missing: "gray" }[status] as TrafficLight;
}

export function reportCard(report: BudgetReport): Attachment {
  const approvalData = {
    approvalId: report.report_id,
    reportId: report.report_id,
    title: `${report.project_name} budget recommendation`,
  };
  return CardFactory.adaptiveCard({
    type: "AdaptiveCard",
    version: "1.5",
    body: [
      { type: "TextBlock", text: "Engineering Budget Evaluation", weight: "Bolder", size: "Large" },
      { type: "TextBlock", text: report.project_name, wrap: true },
      {
        type: "FactSet",
        facts: [
          { title: "Construction area", value: `${report.construction_area_sqm.toFixed(2)} Sqm` },
          { title: "PER Budget", value: usd(report.per_budget_total_usd) },
          { title: "QS Estimate", value: usd(report.qs_total_usd) },
          { title: "Historical unit rate", value: `${usd(report.historical_weighted_unit_rate_usd_sqm)}/Sqm` },
        ],
      },
      {
        type: "TextBlock",
        text: "Status: 🟢 approve/reasonable  🟡 conditional/review  🔴 reject/significant concern  ⚪ benchmark missing",
        wrap: true,
        size: "Small",
        isSubtle: true,
      },
      {
        type: "Container",
        separator: true,
        items: [
          {
            type: "TextBlock",
            text: "Page 1 — Vendor Total vs PER Budget",
            weight: "Bolder",
            size: "Medium",
            color: "Accent",
          },
          {
            type: "TextBlock",
            text: "🟢 within ±10%: approve; 🟡 above ±10% to ±20%: conditional approval; 🔴 above ±20%: reject.",
            size: "Small",
            isSubtle: true,
            wrap: true,
          },
          ...report.vendors.map(pageOneVendor),
        ],
      },
      comparisonPage(
        "Page 2 — Vendor Category Amount vs QS Estimate",
        "🟢 within ±5%: reasonable; 🟡 above ±5% to ±15%: review required; 🔴 above ±15%: significant cost concern. The table shows each vendor's highest-priority exceptions.",
        report.vendors,
        (vendor) => vendor.qs_comparisons,
        false,
      ),
      comparisonPage(
        "Page 3 — Vendor Category Unit Rate vs Historical Unit Rate",
        "All values are compared in USD/Sqm. 🟢 within ±5%: reasonable; 🟡 above ±5% to ±15%: review required; 🔴 above ±15%: significant cost concern.",
        report.vendors,
        (vendor) => vendor.historical_comparisons,
        true,
      ),
      scopeComparisonPage(report.scope_comparisons),
      {
        type: "TextBlock",
        text: report.executive_summary ?? "The structured evaluation is complete.",
        wrap: true,
        separator: true,
      },
      {
        type: "TextBlock",
        text: `Report ID: ${report.report_id}. Ask questions across all uploaded files, including calculations. Use [filename] question to chat with one file, or type files to list available documents.`,
        isSubtle: true,
        wrap: true,
      },
    ],
    actions: [
      {
        type: "Action.Execute",
        title: "Approve",
        verb: "approve",
        data: approvalData,
        fallback: {
          type: "Action.Submit",
          title: "Approve",
          data: { ...approvalData, action: "approve" },
        },
      },
    ],
  });
}

const REQUIRED_UPLOADS = [
  { id: "project_summary", name: "Project Summary", hint: "Project name and construction area" },
  { id: "per_budget", name: "PER Budget", hint: "Budget categories and amounts" },
  { id: "qs_estimate", name: "QS Estimate", hint: "QS categories and estimate amounts" },
  { id: "vendor_quotation", name: "Vendor Quotations", hint: "Line items and prices for each vendor" },
  { id: "mapping_rules", name: "Mapping Rules", hint: "Vendor WBS description to benchmark category" },
  { id: "historical_rates", name: "Historical Unit Rates", hint: "Category rates in USD/Sqm" },
];

export function uploadGuideCard(status?: SourceStatus): Attachment {
  const recognized = new Set(status?.recognized_sources.map((source) => source.id) ?? []);
  return CardFactory.adaptiveCard({
    type: "AdaptiveCard",
    version: "1.5",
    body: [
      { type: "TextBlock", text: "Upload Budget Source Files", weight: "Bolder", size: "Large" },
      {
        type: "TextBlock",
        text: "Upload the following sources in one or multiple messages. Supported formats: PDF, DOC/DOCX, and XLS/XLSX. A single file may contain multiple sources.",
        wrap: true,
      },
      {
        type: "Table",
        firstRowAsHeaders: true,
        showGridLines: true,
        columns: [{ width: 1 }, { width: 2 }, { width: 3 }],
        rows: [
          {
            type: "TableRow",
            cells: [
              tableCell("Status", "Accent", true),
              tableCell("Required source / suggested tab name", "Accent", true),
              tableCell("Required information", "Accent", true),
            ],
          },
          ...REQUIRED_UPLOADS.map((source) => ({
            type: "TableRow",
            cells: [
              tableCell(recognized.has(source.id) ? "✅ Received" : "⬆️ Upload"),
              tableCell(source.name, recognized.has(source.id) ? "Good" : "Attention", true),
              tableCell(source.hint),
            ],
          })),
        ],
      },
      {
        type: "TextBlock",
        text: status && !status.complete
          ? `Still required: ${status.missing_sources.map((source) => source.name).join(", ")}. Please upload the missing file(s).`
          : "The evaluation starts automatically after all six source categories are available.",
        wrap: true,
        weight: "Bolder",
        color: status && !status.complete ? "Attention" : "Accent",
      },
    ],
  });
}

export function errorCard(title: string, detail: string): Attachment {
  return CardFactory.adaptiveCard({
    type: "AdaptiveCard",
    version: "1.5",
    body: [
      { type: "TextBlock", text: title, weight: "Bolder", color: "Attention" },
      { type: "TextBlock", text: detail, wrap: true },
    ],
  });
}

export function approvalCompletedCard(result: ApprovalResult): Attachment {
  return CardFactory.adaptiveCard(approvalCompletedCardContent(result));
}

export function approvalCompletedCardContent(result: ApprovalResult) {
  return {
    type: "AdaptiveCard",
    version: "1.5",
    body: [
      {
        type: "TextBlock",
        text: "✅ Approved",
        weight: "Bolder",
        size: "Medium",
        color: "Good",
      },
      {
        type: "TextBlock",
        text: result.title,
        wrap: true,
      },
      {
        type: "FactSet",
        facts: [
          { title: "Approved by", value: result.approvedBy },
          { title: "Approved at", value: result.approvedAt },
          { title: "Status", value: "Completed — no further action is required" },
        ],
      },
    ],
  };
}
