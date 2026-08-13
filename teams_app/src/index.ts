import * as restify from "restify";
import {
  CloudAdapter,
  ConfigurationBotFrameworkAuthentication,
  ConfigurationServiceClientCredentialFactory,
  TurnContext,
} from "botbuilder";
import { config } from "./config";
import { TeamsBot } from "./teamsBot";

const credentialsFactory = new ConfigurationServiceClientCredentialFactory({
  MicrosoftAppId: config.appId,
  MicrosoftAppPassword: config.appPassword,
  MicrosoftAppType: config.appType,
  MicrosoftAppTenantId: config.appTenantId,
});
const authentication = new ConfigurationBotFrameworkAuthentication({}, credentialsFactory);
const adapter = new CloudAdapter(authentication);
adapter.onTurnError = async (context: TurnContext, error: Error) => {
  console.error("[onTurnError]", error);
  await context.sendActivity("Bot 处理消息时发生错误。");
};

const bot = new TeamsBot();
const server = restify.createServer();
server.use(restify.plugins.bodyParser());
server.post("/api/messages", async (req, res) => {
  await adapter.process(req, res, (context) => bot.run(context));
});
server.get("/healthz", (_req, res, next) => {
  res.send(200, { status: "ok", mcpUrl: config.mcpUrl });
  return next();
});
server.listen(config.port, () => {
  console.log(`Teams app listening on :${config.port}`);
});
