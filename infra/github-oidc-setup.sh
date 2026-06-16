#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
#  MD Sign Creator — GitHub ↔ Azure OIDC trust setup
#
#  Allows GitHub Actions to authenticate with Azure using short-lived tokens
#  (no long-lived secrets stored in GitHub).
#
#  Run this ONCE after azure-setup.sh.
#  Prerequisites:
#    - azure-setup.sh must have been run first
#    - Logged in with az login using an account with Owner/User Access Admin role
#
#  Usage:
#    bash infra/github-oidc-setup.sh
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
RESOURCE_GROUP="md-sign-creator-rg"
GITHUB_ORG="SethSterling22"
GITHUB_REPO="MD_Sign_Creator"
APP_DISPLAY_NAME="md-sign-creator-github-actions"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   GitHub ↔ Azure OIDC Federation Setup                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Get subscription ID ────────────────────────────────────────────────────
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

# ── 2. Create App Registration ────────────────────────────────────────────────
echo "▶ Creating Azure AD App Registration..."
APP_ID=$(az ad app create \
  --display-name "$APP_DISPLAY_NAME" \
  --query appId -o tsv)

# ── 3. Create Service Principal ───────────────────────────────────────────────
echo "▶ Creating Service Principal..."
SP_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)

# Wait a moment for propagation
sleep 10

# ── 4. Assign Contributor role on the resource group ─────────────────────────
echo "▶ Assigning Contributor role on resource group $RESOURCE_GROUP..."
az role assignment create \
  --assignee "$SP_ID" \
  --role Contributor \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP" \
  --output none

# ── 5. Add federated credentials (main branch) ───────────────────────────────
echo "▶ Adding federated credential for branch: main..."
az ad app federated-credential create \
  --id "$APP_ID" \
  --parameters "{
    \"name\": \"github-main\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:${GITHUB_ORG}/${GITHUB_REPO}:ref:refs/heads/main\",
    \"description\": \"GitHub Actions deploy from main branch\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }" \
  --output none

# ── 6. Output GitHub Secrets ──────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   ✅  OIDC federation configured!                         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Add these 3 secrets to your GitHub repository:"
echo "  Settings → Secrets and variables → Actions → New repository secret"
echo ""
echo "  ┌─────────────────────────────────────────────────────────┐"
echo "  │  AZURE_CLIENT_ID       = $APP_ID"
echo "  │  AZURE_TENANT_ID       = $TENANT_ID"
echo "  │  AZURE_SUBSCRIPTION_ID = $SUBSCRIPTION_ID"
echo "  └─────────────────────────────────────────────────────────┘"
echo ""
echo "  Once secrets are set, push to main to trigger a deploy."
echo ""
