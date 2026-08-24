#!/usr/bin/env bash
set -euo pipefail

: "${MCP_URL:?Set MCP_URL to the deployed sandbox MCP endpoint}"

RG="${AZURE_RESOURCE_GROUP:-rg-budget-agent}"
LOCATION="${AZURE_LOCATION:-eastus2}"
SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"
TENANT_ID="${AZURE_TENANT_ID:-$(az account show --query tenantId -o tsv)}"
SUFFIX="$(printf '%s' "$SUBSCRIPTION_ID" | tr -d '-' | cut -c1-8)"
ACR="${AZURE_ACR_NAME:-acrbudgetagent${SUFFIX}}"
ENVIRONMENT="${AZURE_CONTAINERAPP_ENV:-aca-env-budget-agent}"
APP="${AZURE_TEAMS_APP_NAME:-aca-teams-budget-agent}"
BOT="${AZURE_BOT_NAME:-bot-budget-agent-${SUFFIX}}"
APP_DISPLAY_NAME="${AZURE_BOT_APP_DISPLAY_NAME:-Engineering Budget Agent}"
IMAGE_TAG="${AZURE_IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"
IMAGE="${ACR}.azurecr.io/engineering-budget-teams:${IMAGE_TAG}"

az acr show -g "$RG" -n "$ACR" >/dev/null 2>&1 \
  || az acr create -g "$RG" -n "$ACR" -l "$LOCATION" --sku Basic --admin-enabled false -o none
az acr build -r "$ACR" -t "engineering-budget-teams:${IMAGE_TAG}" teams_app --no-logs -o none
az containerapp env show -g "$RG" -n "$ENVIRONMENT" >/dev/null 2>&1 \
  || az containerapp env create -g "$RG" -n "$ENVIRONMENT" -l "$LOCATION" -o none

APP_ID="$(az ad app list --display-name "$APP_DISPLAY_NAME" --query '[0].appId' -o tsv)"
if [[ -z "$APP_ID" ]]; then
  APP_ID="$(az ad app create \
    --display-name "$APP_DISPLAY_NAME" \
    --sign-in-audience AzureADMyOrg \
    --query appId -o tsv)"
  az ad sp create --id "$APP_ID" -o none
fi
az ad app update --id "$APP_ID" --sign-in-audience AzureADMyOrg
APP_PASSWORD="$(az ad app credential reset --id "$APP_ID" --append --years 1 --query password -o tsv)"

if az containerapp show -g "$RG" -n "$APP" >/dev/null 2>&1; then
  az containerapp secret set -g "$RG" -n "$APP" --secrets bot-password="$APP_PASSWORD" -o none
  az containerapp update -g "$RG" -n "$APP" \
    --image "$IMAGE" \
    --set-env-vars \
      MicrosoftAppType=SingleTenant \
      MicrosoftAppId="$APP_ID" \
      MicrosoftAppTenantId="$TENANT_ID" \
      MicrosoftAppPassword=secretref:bot-password \
      MCP_URL="$MCP_URL" \
    -o none
else
  az containerapp create -g "$RG" -n "$APP" \
    --environment "$ENVIRONMENT" \
    --image "$IMAGE" \
    --registry-server "${ACR}.azurecr.io" \
    --registry-identity system \
    --ingress external \
    --target-port 3978 \
    --min-replicas 0 \
    --max-replicas 1 \
    --secrets bot-password="$APP_PASSWORD" \
    --env-vars \
      MicrosoftAppType=SingleTenant \
      MicrosoftAppId="$APP_ID" \
      MicrosoftAppTenantId="$TENANT_ID" \
      MicrosoftAppPassword=secretref:bot-password \
      MCP_URL="$MCP_URL" \
    -o none
fi

FQDN="$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
ENDPOINT="https://${FQDN}/api/messages"
if az bot show -g "$RG" -n "$BOT" >/dev/null 2>&1; then
  az bot update -g "$RG" -n "$BOT" --endpoint "$ENDPOINT" -o none
else
  az bot create -g "$RG" -n "$BOT" \
    --appid "$APP_ID" \
    --app-type SingleTenant \
    --tenant-id "$TENANT_ID" \
    --endpoint "$ENDPOINT" \
    --sku F0 \
    --display-name "Engineering Budget Agent" \
    -o none
fi
az bot msteams show -g "$RG" -n "$BOT" >/dev/null 2>&1 \
  || az bot msteams create -g "$RG" -n "$BOT" \
    --add-disabled false \
    --enable-calling false \
    -o none

mkdir -p .azure/teams-package
sed "s/\${{MICROSOFT_APP_ID}}/${APP_ID}/g" \
  teams_app/appManifest/manifest.json > .azure/teams-package/manifest.json
cp teams_app/appManifest/color.png teams_app/appManifest/outline.png .azure/teams-package/
(cd .azure/teams-package && zip -q -r ../engineering-budget-teams-app.zip .)

cat > .azure/teams-deployment.json <<JSON
{
  "appId": "${APP_ID}",
  "botName": "${BOT}",
  "containerApp": "${APP}",
  "messagingEndpoint": "${ENDPOINT}",
  "teamsPackage": ".azure/engineering-budget-teams-app.zip"
}
JSON
cat .azure/teams-deployment.json
