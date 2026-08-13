import { ActivityHandler, TurnContext } from "botbuilder";
import { budgetMcp } from "./mcpClient";
import { errorCard, reportCard } from "./cards";

const HELP =
  "请上传包含 `PER Budget`、`QS Estimation`、`Vendor Quotation`、`MAPPING RULES`、" +
  "`Historical Unit Rates` 和 `Summary` 的 `.xlsx` 文件。评估后可在同一会话继续追问。";

interface TeamsDownloadInfo {
  downloadUrl?: string;
  name?: string;
  fileType?: string;
}

export class TeamsBot extends ActivityHandler {
  private readonly conversationReports = new Map<string, string>();

  constructor() {
    super();
    this.onMessage(async (context, next) => {
      TurnContext.removeRecipientMention(context.activity);
      const text = (context.activity.text ?? "").trim();
      const attachment = context.activity.attachments?.find((item) => {
        const name = String(item.name ?? (item.content as TeamsDownloadInfo | undefined)?.name ?? "");
        return name.toLowerCase().endsWith(".xlsx");
      });

      if (attachment) {
        await context.sendActivity("已收到 Excel，正在按 Mapping Rules 和 Sqm 单价进行评估…");
        try {
          const info = (attachment.content ?? {}) as TeamsDownloadInfo;
          const url = info.downloadUrl ?? attachment.contentUrl;
          const filename = attachment.name ?? info.name ?? "budget.xlsx";
          if (!url) throw new Error("Teams attachment does not include a download URL.");
          const response = await fetch(url);
          if (!response.ok) throw new Error(`Excel download failed: HTTP ${response.status}`);
          const report = await budgetMcp.evaluate(filename, Buffer.from(await response.arrayBuffer()));
          this.conversationReports.set(context.activity.conversation.id, report.report_id);
          await context.sendActivity({ attachments: [reportCard(report)] });
        } catch (error) {
          await context.sendActivity({
            attachments: [errorCard("预算评估失败", error instanceof Error ? error.message : String(error))],
          });
        }
      } else if (/^help$/i.test(text) || !text) {
        await context.sendActivity(HELP);
      } else {
        const reportId = this.conversationReports.get(context.activity.conversation.id);
        if (!reportId) {
          await context.sendActivity(HELP);
        } else {
          await context.sendActivity("正在分析当前预算报告…");
          try {
            await context.sendActivity(await budgetMcp.ask(reportId, text));
          } catch (error) {
            await context.sendActivity({
              attachments: [errorCard("追问失败", error instanceof Error ? error.message : String(error))],
            });
          }
        }
      }
      await next();
    });

    this.onMembersAdded(async (context, next) => {
      await context.sendActivity(HELP);
      await next();
    });
  }
}
