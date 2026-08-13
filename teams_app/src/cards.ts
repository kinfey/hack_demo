import { Attachment, CardFactory } from "botbuilder";
import { BudgetReport, Comparison, VendorAssessment } from "./mcpClient";

type TrafficLight = "green" | "yellow" | "red" | "gray";

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
  approve: "批准",
  conditional_approval: "有条件批准",
  reject: "拒绝",
  reasonable: "合理",
  review_required: "需要复核",
  significant_concern: "重大成本风险",
  benchmark_missing: "缺少基准",
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
          { title: "Vendor 总价", value: usd(vendor.total_amount_usd) },
          { title: "单价", value: `${usd(vendor.unit_rate_usd_sqm)}/Sqm` },
          { title: "对 PER 偏差", value: pct(vendor.per_budget_variance_pct) },
          { title: "建议值", value: usd(vendor.recommended_value_usd) },
          { title: "潜在节省", value: usd(vendor.potential_savings_usd) },
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
      text: `${vendor.vendor}：${statusCounts(comparisons)}`,
      weight: "Bolder",
      separator: true,
      wrap: true,
    });
    for (const item of priorityComparisons(comparisons)) {
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
      items.push({
        type: "TextBlock",
        text: `${icon(item.status_color)} ${item.category}: ${vendorValue} vs ${benchmark} (${pct(item.variance_pct)}) — ${decision(item.decision)}`,
        color: color(item.status_color),
        size: "Small",
        wrap: true,
        spacing: "Small",
      });
    }
  }

  return { type: "Container", separator: true, items };
}

export function reportCard(report: BudgetReport): Attachment {
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
      {
        type: "TextBlock",
        text: "颜色规则：🟢 批准/合理　🟡 有条件批准/需要复核　🔴 拒绝/重大成本风险　⚪ 缺少基准",
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
            text: "Page 1 — Vendor 总价 vs PER Budget",
            weight: "Bolder",
            size: "Medium",
            color: "Accent",
          },
          {
            type: "TextBlock",
            text: "🟢 ±10% 内批准；🟡 超过 ±10% 至 ±20% 有条件批准；🔴 超过 ±20% 拒绝。",
            size: "Small",
            isSubtle: true,
            wrap: true,
          },
          ...report.vendors.map(pageOneVendor),
        ],
      },
      comparisonPage(
        "Page 2 — Vendor 分类金额 vs QS Estimate",
        "🟢 ±5% 内合理；🟡 超过 ±5% 至 ±15% 需要复核；🔴 超过 ±15% 为重大成本风险。每家展示状态统计及优先风险项。",
        report.vendors,
        (vendor) => vendor.qs_comparisons,
        false,
      ),
      comparisonPage(
        "Page 3 — Vendor 分类单价 vs Historical Unit Rate",
        "全部按 USD/Sqm 对比。🟢 ±5% 内合理；🟡 超过 ±5% 至 ±15% 需要复核；🔴 超过 ±15% 为重大成本风险。",
        report.vendors,
        (vendor) => vendor.historical_comparisons,
        true,
      ),
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
