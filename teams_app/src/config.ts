import "dotenv/config";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

export const config = {
  port: Number(process.env.PORT ?? "3978"),
  appId: required("MicrosoftAppId"),
  appPassword: required("MicrosoftAppPassword"),
  appType: process.env.MicrosoftAppType ?? "SingleTenant",
  appTenantId: process.env.MicrosoftAppTenantId ?? "",
  mcpUrl: required("MCP_URL"),
  mcpTimeoutMs: Number(process.env.MCP_TIMEOUT_MS ?? "240000"),
};
