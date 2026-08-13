import { Attachment, CardFactory } from "botbuilder";
import { BudgetReport } from "./mcpClient";

const usd = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

const pct = (value: number) => `${(value * 100).toFixed(1)}%`;

export function reportCard(report: BudgetReport): Attachment {
  const vendors = report.vendors.map((vendor) => ({
    type: "FactSet",
    facts: [
      { title: vendor.vendor, value: `${usd(vendor.total_amount_usd)} | ${usd(vendor.unit_rate_usd_sqm)}/Sqm` },
      { title: "vs PER", value: `${pct(vendor.per_budget_variance_pct)} | ${vendor.per_budget_decision}` },
    ],
  }));
  return CardFactory.adaptiveCard({
    type: "AdaptiveCard",
    version: "1.5",
    body: [
      { type: "TextBlock", text: "工程预算评估", weight: "Bolder", size: "Large" },
      { type: "TextBlock", text: report.project_name, wrap: true },
      {
        type: "FactSet",
        facts: [
          { title: "面积", value: `${report.construction_area_sqm.toFixed(2)} Sqm` },
          { title: "PER Budget", value: usd(report.per_budget_total_usd) },
          { title: "QS Estimate", value: usd(report.qs_total_usd) },
          { title: "历史单价", value: `${usd(report.historical_weighted_unit_rate_usd_sqm)}/Sqm` },
        ],
      },
      ...vendors,
      {
        type: "TextBlock",
        text: report.executive_summary ?? "结构化评估已完成。",
        wrap: true,
        separator: true,
      },
      {
        type: "TextBlock",
        text: `Report ID: ${report.report_id}。可继续在当前会话中追问。`,
        isSubtle: true,
        wrap: true,
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
