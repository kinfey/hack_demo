import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { config } from "./config";

export interface Comparison {
  category: string;
  variance_pct: number | null;
  decision: string;
}

export interface VendorAssessment {
  vendor: string;
  total_amount_usd: number;
  unit_rate_usd_sqm: number;
  per_budget_variance_pct: number;
  per_budget_decision: string;
  potential_savings_usd: number;
  qs_comparisons: Comparison[];
  historical_comparisons: Comparison[];
}

export interface BudgetReport {
  report_id: string;
  project_name: string;
  construction_area_sqm: number;
  per_budget_total_usd: number;
  qs_total_usd: number;
  historical_weighted_unit_rate_usd_sqm: number;
  vendors: VendorAssessment[];
  unmatched_vendor_items: string[];
  warnings: string[];
  executive_summary: string | null;
}

class BudgetMcpClient {
  private async withClient<T>(fn: (client: Client) => Promise<T>): Promise<T> {
    const transport = new StreamableHTTPClientTransport(new URL(config.mcpUrl));
    const client = new Client(
      { name: "engineering-budget-teams-app", version: "0.1.0" },
      { capabilities: {} }
    );
    try {
      await client.connect(transport);
      return await fn(client);
    } finally {
      await client.close().catch(() => undefined);
    }
  }

  private structured<T>(result: any): T {
    if (result?.structuredContent) return result.structuredContent as T;
    const text = result?.content?.find((block: any) => block?.type === "text")?.text;
    if (!text) throw new Error("MCP tool returned no structured content");
    return JSON.parse(text) as T;
  }

  async evaluate(filename: string, content: Buffer): Promise<BudgetReport> {
    return this.withClient(async (client) => {
      const result = await client.callTool(
        {
          name: "evaluate_budget_workbook",
          arguments: {
            filename,
            file_base64: content.toString("base64"),
            include_ai_summary: true,
            language: "zh-CN",
          },
        },
        undefined,
        { timeout: config.mcpTimeoutMs, resetTimeoutOnProgress: true }
      );
      return this.structured<BudgetReport>(result);
    });
  }

  async ask(reportId: string, question: string): Promise<string> {
    return this.withClient(async (client) => {
      const result = await client.callTool(
        {
          name: "ask_budget_report",
          arguments: { report_id: reportId, question, language: "zh-CN" },
        },
        undefined,
        { timeout: config.mcpTimeoutMs, resetTimeoutOnProgress: true }
      );
      return this.structured<{ answer: string }>(result).answer;
    });
  }
}

export const budgetMcp = new BudgetMcpClient();
