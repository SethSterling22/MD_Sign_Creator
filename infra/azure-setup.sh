#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
#  MD Sign Creator — Azure Container Apps — One-time infrastructure setup
#
#  Run this ONCE to create all Azure resources.
#  Prerequisites:
#    - Azure CLI installed & logged in:  az login
#    - Correct subscription selected:   az account set --subscription <id>
#    - A GitHub PAT with read:packages scope (for pulling from GHCR)
#
#  Usage:
#    GITHUB_USERNAME=SethSterling22 \
#    GHCR_PAT=ghp_xxxx \
#    bash infra/azure-setup.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Config (edit these if needed) ────────────────────────────────────────────
RESOURCE_GROUP="md-sign-creator-rg"
LOCATION="eastus"                          # change to your preferred region
ENVIRONMENT="md-sign-creator-env"
APP_NAME="md-sign-creator"
IMAGE="ghcr.io/sethsterling22/md_sign_creator:latest"
MIN_REPLICAS=0                             # scale to zero when idle → $0 cost
MAX_REPLICAS=1
CPU="0.25"                                 # smallest available vCPU
MEMORY="0.5Gi"                             # smallest available memory
TARGET_PORT=5000                           # Gunicorn port inside the container

# ── Validate required env vars ────────────────────────────────────────────────
: "${GITHUB_USERNAME:?Set GITHUB_USERNAME before running}"
: "${GHCR_PAT:?Set GHCR_PAT (GitHub PAT with read:packages) before running}"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   MD Sign Creator — Azure Container Apps Setup           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Resource group : $RESOURCE_GROUP"
echo "  Location       : $LOCATION"
echo "  App name       : $APP_NAME"
echo "  Image          : $IMAGE"
echo "  Scale          : $MIN_REPLICAS–$MAX_REPLICAS replicas"
echo "  Resources      : $CPU vCPU · $MEMORY RAM"
echo ""

# ── 1. Resource group ─────────────────────────────────────────────────────────
echo "▶ Creating resource group..."
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

# ── 2. Log Analytics workspace (required by Container Apps environment) ───────
echo "▶ Creating Log Analytics workspace..."
WORKSPACE_ID=$(az monitor log-analytics workspace create \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "${APP_NAME}-logs" \
  --location "$LOCATION" \
  --query customerId -o tsv)

WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group "$RESOURCE_GROUP" \
  --workspace-name "${APP_NAME}-logs" \
  --query primarySharedKey -o tsv)

# ── 3. Container Apps environment ─────────────────────────────────────────────
echo "▶ Creating Container Apps environment..."
az containerapp env create \
  --name "$ENVIRONMENT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --logs-workspace-id "$WORKSPACE_ID" \
  --logs-workspace-key "$WORKSPACE_KEY" \
  --output none

# ── 4. Container App ──────────────────────────────────────────────────────────
echo "▶ Creating Container App (scale-to-zero enabled)..."
az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENVIRONMENT" \
  --image "$IMAGE" \
  --registry-server ghcr.io \
  --registry-username "$GITHUB_USERNAME" \
  --registry-password "$GHCR_PAT" \
  --target-port "$TARGET_PORT" \
  --ingress external \
  --min-replicas "$MIN_REPLICAS" \
  --max-replicas "$MAX_REPLICAS" \
  --cpu "$CPU" \
  --memory "$MEMORY" \
  --output none

# ── 5. Print result ───────────────────────────────────────────────────────────
APP_URL=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   ✅  Infrastructure ready!                               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  App URL: https://$APP_URL"
echo ""
echo "  Next step: run infra/github-oidc-setup.sh to enable"
echo "  automatic deploys from GitHub Actions."
echo ""
