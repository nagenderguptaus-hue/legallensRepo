#!/usr/bin/env bash
# One-time setup so that .github/workflows/cd.yml can log in to Azure and deploy to AKS.
#
# What it does (run it yourself; it changes your Azure subscription and GitHub repository):
#   1. Creates an Entra app registration with a federated (OIDC) credential for GitHub Actions.
#      No password or client secret is created.
#   2. Gives that identity the roles cd.yml needs: AcrPush on the registry, and cluster access
#      on the AKS cluster (get credentials, apply manifests).
#   3. Prints the GitHub repository variables and the `dev` environment to create.
#
# Prerequisites: Azure CLI (`az login` done, Owner or User Access Administrator on the
# subscription), and the resource group, ACR and AKS cluster from CD_readme.md already exist.
# Run it from Git Bash. Safe to re-run: existing objects are reused.
#
#   bash deploy/setup-cd.sh
#
# Override any value with an environment variable, for example:
#   ACR_NAME=acrlegallens1234 bash deploy/setup-cd.sh

set -euo pipefail

GH_REPO="${GH_REPO:-nagenderguptaus-hue/legallensRepo}"
RG="${RG:-rg-legallens-dev}"
ACR_NAME="${ACR_NAME:-acrlegallens7kq2}"
AKS_NAME="${AKS_NAME:-aks-legallens-dev}"
APP_NAME="${APP_NAME:-github-legallens-cd}"

OWNER="${GH_REPO%%/*}"
REPO="${GH_REPO#*/}"
ISSUER="https://token.actions.githubusercontent.com"
AUDIENCE="api://AzureADTokenExchange"

say() { printf '\n== %s\n' "$*"; }

say "Azure account"
TENANT_ID=$(az account show --query tenantId -o tsv)
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "subscription: $(az account show --query name -o tsv)"

say "App registration and service principal: $APP_NAME"
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [ -z "$APP_ID" ]; then
  APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
  echo "created app $APP_ID"
else
  echo "reusing app $APP_ID"
fi
if ! az ad sp show --id "$APP_ID" >/dev/null 2>&1; then
  az ad sp create --id "$APP_ID" >/dev/null
fi
SP_OBJECT_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)

say "Federated credentials (GitHub OIDC, no secret)"
# publish job (runs after backend-ci on main, or a manual run from main): subject uses the ref.
# deploy job (environment: dev): subject uses the environment name.
add_fic() {
  local name="$1" subject="$2"
  if az ad app federated-credential list --id "$APP_ID" --query "[?name=='$name'] | [0].name" -o tsv | grep -q .; then
    echo "exists: $name"
  else
    az ad app federated-credential create --id "$APP_ID" --parameters "{
      \"name\": \"$name\",
      \"issuer\": \"$ISSUER\",
      \"subject\": \"$subject\",
      \"audiences\": [\"$AUDIENCE\"]
    }" >/dev/null
    echo "created: $name ($subject)"
  fi
}
add_fic "gh-main" "repo:$OWNER/$REPO:ref:refs/heads/main"
add_fic "gh-env-dev" "repo:$OWNER/$REPO:environment:dev"

say "Role assignments"
ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$RG" --query id -o tsv)
AKS_ID=$(az aks show --name "$AKS_NAME" --resource-group "$RG" --query id -o tsv)

AAD_PROFILE=$(az aks show --name "$AKS_NAME" --resource-group "$RG" --query aadProfile -o json 2>/dev/null || true)
if ! printf '%s' "$AAD_PROFILE" | grep -qi '"enableazurerbac": *true'; then
  echo "WARNING: Azure RBAC for Kubernetes does not look enabled on $AKS_NAME."
  echo "         The RBAC Writer role below has no effect until it is enabled, and the deploy job will fail."
  echo "         Enable it with: az aks update -g $RG -n $AKS_NAME --enable-aad --enable-azure-rbac"
fi

assign() {
  local role="$1" scope="$2"
  if [ -n "$(az role assignment list --assignee-object-id "$SP_OBJECT_ID" --scope "$scope" --role "$role" --query '[0].id' -o tsv)" ]; then
    echo "exists: $role"
  else
    az role assignment create --assignee-object-id "$SP_OBJECT_ID" --assignee-principal-type ServicePrincipal \
      --role "$role" --scope "$scope" >/dev/null
    echo "assigned: $role"
  fi
}
assign "AcrPush" "$ACR_ID"
assign "Azure Kubernetes Service Cluster User Role" "$AKS_ID"
assign "Azure Kubernetes Service RBAC Writer" "$AKS_ID"

say "GitHub settings (copy these; no secrets are involved)"
cat <<EOF
Repository variables (Settings > Secrets and variables > Actions > Variables), or with gh:

  gh variable set AZURE_CLIENT_ID --repo $GH_REPO --body "$APP_ID"
  gh variable set AZURE_TENANT_ID --repo $GH_REPO --body "$TENANT_ID"
  gh variable set AZURE_SUBSCRIPTION_ID --repo $GH_REPO --body "$SUBSCRIPTION_ID"
  gh variable set AZURE_RESOURCE_GROUP --repo $GH_REPO --body "$RG"
  gh variable set ACR_NAME --repo $GH_REPO --body "$ACR_NAME"
  gh variable set AKS_NAME --repo $GH_REPO --body "$AKS_NAME"

Environment "dev" (Settings > Environments > New environment, name: dev).
Create it once; cd.yml's deploy job uses it. Required reviewers are optional.
EOF
echo
echo "Done. Role assignments can take a few minutes to take effect."
