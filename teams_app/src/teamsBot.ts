import { ActivityHandler, TurnContext } from "botbuilder";
import { budgetMcp, UploadedBudgetDocument } from "./mcpClient";
import { errorCard, reportCard, uploadGuideCard } from "./cards";

const SUPPORTED_FILE = /\.(pdf|docx?|xlsx?)$/i;

interface TeamsDownloadInfo {
  downloadUrl?: string;
  name?: string;
  fileType?: string;
}

export class TeamsBot extends ActivityHandler {
  private readonly conversationReports = new Map<
    string,
    { reportId: string; documentNames: string[] }
  >();
  private readonly conversationDocuments = new Map<string, Map<string, Buffer>>();

  constructor() {
    super();
    this.onMessage(async (context, next) => {
      TurnContext.removeRecipientMention(context.activity);
      const text = (context.activity.text ?? "").trim();
      const attachments = (context.activity.attachments ?? []).filter((item) => {
        const name = String(item.name ?? (item.content as TeamsDownloadInfo | undefined)?.name ?? "");
        return SUPPORTED_FILE.test(name);
      });

      if (attachments.length > 0) {
        await context.sendActivity("Files received. Checking the required budget sources...");
        try {
          const conversationId = context.activity.conversation.id;
          const stored = this.conversationDocuments.get(conversationId) ?? new Map<string, Buffer>();
          const downloaded = await Promise.all(attachments.map(async (attachment) => {
            const info = (attachment.content ?? {}) as TeamsDownloadInfo;
            const url = info.downloadUrl ?? attachment.contentUrl;
            const filename = attachment.name ?? info.name ?? "budget-source";
            if (!url) throw new Error(`${filename}: Teams did not provide a download URL.`);
            const response = await fetch(url);
            if (!response.ok) throw new Error(`${filename}: download failed with HTTP ${response.status}.`);
            return { filename, content: Buffer.from(await response.arrayBuffer()) };
          }));
          for (const document of downloaded) stored.set(document.filename, document.content);
          this.conversationDocuments.set(conversationId, stored);

          const documents: UploadedBudgetDocument[] = [...stored].map(([filename, content]) => ({
            filename,
            content,
          }));
          const status = await budgetMcp.inspect(documents);
          if (!status.complete) {
            await context.sendActivity({ attachments: [uploadGuideCard(status)] });
          } else {
            await context.sendActivity("All required sources are available. Running the evaluation...");
            const report = await budgetMcp.evaluate(documents);
            this.conversationReports.set(conversationId, {
              reportId: report.report_id,
              documentNames: report.document_names,
            });
            this.conversationDocuments.delete(conversationId);
            await context.sendActivity({ attachments: [reportCard(report)] });
          }
        } catch (error) {
          await context.sendActivity({
            attachments: [errorCard("Budget evaluation failed", error instanceof Error ? error.message : String(error))],
          });
        }
      } else if (/^help$/i.test(text) || !text) {
        await context.sendActivity({ attachments: [uploadGuideCard()] });
      } else {
        const report = this.conversationReports.get(context.activity.conversation.id);
        if (!report) {
          await context.sendActivity({ attachments: [uploadGuideCard()] });
        } else if (/^(files|文件|文档)$/i.test(text)) {
          await context.sendActivity(
            `可对话文件：\n${report.documentNames.map((name) => `- ${name}`).join("\n")}`
          );
        } else {
          const scopedQuestion = /^\[([^\]]+)\]\s*(.+)$/s.exec(text);
          const requestedFilename = scopedQuestion?.[1]?.trim();
          const question = scopedQuestion?.[2]?.trim() ?? text;
          const filename = requestedFilename
            ? report.documentNames.find(
                (name) => name.toLocaleLowerCase() === requestedFilename.toLocaleLowerCase()
              )
            : undefined;
          if (requestedFilename && !filename) {
            await context.sendActivity(
              `未找到文件 "${requestedFilename}"。可用文件：\n`
              + report.documentNames.map((name) => `- ${name}`).join("\n")
            );
            await next();
            return;
          }
          await context.sendActivity("Analyzing the current budget report...");
          try {
            await context.sendActivity(await budgetMcp.ask(report.reportId, question, filename));
          } catch (error) {
            await context.sendActivity({
              attachments: [errorCard("Follow-up analysis failed", error instanceof Error ? error.message : String(error))],
            });
          }
        }
      }
      await next();
    });

    this.onMembersAdded(async (context, next) => {
      await context.sendActivity({ attachments: [uploadGuideCard()] });
      await next();
    });
  }
}
