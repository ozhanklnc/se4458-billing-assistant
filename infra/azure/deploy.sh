#!/usr/bin/env bash
# Deploys the whole backend to Azure:
#   Azure Database for PostgreSQL Flexible Server  (server database)
#   Azure Container Registry                       (images)
#   Azure Container Apps environment with
#     billing-api  - rejects calls that do not come through the gateway (403)
#     gateway      - Kong, public ingress, the only public entry to the REST API
#     mcp-server   - public ingress, /mcp
#
# Requirements: az CLI (logged in: `az login`), docker, bash, openssl.
# Usage:  ./infra/azure/deploy.sh            (run from the repository root)
set -euo pipefail

PREFIX="${PREFIX:-se4458bill}"
LOCATION="${LOCATION:-westeurope}"     # pick one allowed by your subscription
PG_LOCATION="${PG_LOCATION:-}"          # optional: force the PostgreSQL region(s)
RG="${RG:-rg-$PREFIX}"
SUFFIX="${SUFFIX:-$(echo -n "$(az account show --query id -o tsv)$PREFIX" | shasum | cut -c1-6)}"
ACR="${PREFIX}acr${SUFFIX}"
PG="${PG_NAME:-${PREFIX}-pg-${SUFFIX}}"
ENV_NAME="${PREFIX}-env"
PG_USER="billingadmin"
STATE=".azure-deploy.env"               # generated secrets are kept here (git-ignored)

[ -f "$STATE" ] && source "$STATE"
PG_PASSWORD="${PG_PASSWORD:-P$(openssl rand -hex 12)x}"
JWT_SECRET="${JWT_SECRET:-$(openssl rand -hex 32)}"
GATEWAY_SECRET="${GATEWAY_SECRET:-$(openssl rand -hex 24)}"
printf 'PG_PASSWORD=%s\nJWT_SECRET=%s\nGATEWAY_SECRET=%s\n' "$PG_PASSWORD" "$JWT_SECRET" "$GATEWAY_SECRET" > "$STATE"

echo "==> Resource group $RG ($LOCATION)"
az group create -n "$RG" -l "$LOCATION" -o none
az extension add --name containerapp --upgrade -y -o none
# new subscriptions (e.g. Azure for Students) need these resource providers registered once
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.DBforPostgreSQL Microsoft.ContainerRegistry; do
  az provider register -n "$ns" --wait -o none
done

echo "==> PostgreSQL flexible server $PG"
if ! az postgres flexible-server show -g "$RG" -n "$PG" -o none 2>/dev/null; then
  # Student subscriptions only allow some region/SKU combinations, so try them in order.
  PG_REGIONS="${PG_LOCATION:-$LOCATION spaincentral austriaeast denmarkeast switzerlandnorth}"
  created=""
  for r in $PG_REGIONS; do
    for s in Burstable:Standard_B1ms Burstable:Standard_B2s; do   # the only SKUs Azure for Students allows
      echo "    trying $r ${s#*:}"
      if az postgres flexible-server create -g "$RG" -n "$PG" -l "$r" \
          --tier "${s%%:*}" --sku-name "${s#*:}" --storage-size 32 --version 16 \
          --admin-user "$PG_USER" --admin-password "$PG_PASSWORD" \
          --public-access 0.0.0.0 -y -o none 2>/tmp/pg-create.err; then   # 0.0.0.0 = Azure services only
        created="$r ${s#*:}"; break 2
      fi
      cat /tmp/pg-create.err
    done
  done
  [ -n "$created" ] || { echo "No allowed region/SKU for PostgreSQL in this subscription"; exit 1; }
  echo "    PostgreSQL created: $created"
fi
# the server can need a moment after creation before databases can be added
for i in 1 2 3 4 5; do
  az postgres flexible-server db show -g "$RG" -s "$PG" -d billing -o none 2>/dev/null && break
  az postgres flexible-server db create -g "$RG" -s "$PG" -n billing -o none && break
  echo "    database not ready yet, retrying in 30s"; sleep 30
done
PG_HOST="$PG.postgres.database.azure.com"
DATABASE_URL="postgresql+psycopg://${PG_USER}:${PG_PASSWORD}@${PG_HOST}:5432/billing?sslmode=require"

echo "==> Container registry $ACR + images"
az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled true -o none
az acr login -n "$ACR"
REG="$ACR.azurecr.io"
TAG="$(date +%Y%m%d%H%M%S)"
for svc in billing-api:billing-api mcp-server:mcp-server gateway:gateway/kong; do
  name="${svc%%:*}"; dir="${svc#*:}"
  docker build --platform linux/amd64 -t "$REG/$name:$TAG" "$dir"
  docker push "$REG/$name:$TAG"
done
ACR_PASS="$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv)"

echo "==> Container Apps environment $ENV_NAME"
az containerapp env show -g "$RG" -n "$ENV_NAME" -o none 2>/dev/null || \
  az containerapp env create -g "$RG" -n "$ENV_NAME" -l "$LOCATION" -o none

deploy_app() {   # name image port ingress secrets env...
  local name=$1 image=$2 port=$3 ingress=$4 secrets=$5; shift 5
  local sec_args=() env_create=() env_update=()
  [ -n "$secrets" ] && sec_args=(--secrets $secrets)
  [ $# -gt 0 ] && env_create=(--env-vars "$@") && env_update=(--set-env-vars "$@")
  if az containerapp show -g "$RG" -n "$name" -o none 2>/dev/null; then
    [ -n "$secrets" ] && az containerapp secret set -g "$RG" -n "$name" ${sec_args[@]+"${sec_args[@]}"} -o none
    az containerapp update -g "$RG" -n "$name" --image "$image" ${env_update[@]+"${env_update[@]}"} -o none
  else
    az containerapp create -g "$RG" -n "$name" --environment "$ENV_NAME" --image "$image" \
      --registry-server "$REG" --registry-username "$ACR" --registry-password "$ACR_PASS" \
      --target-port "$port" --ingress "$ingress" --min-replicas 1 --max-replicas 1 \
      --cpu 0.5 --memory 1.0Gi ${sec_args[@]+"${sec_args[@]}"} ${env_create[@]+"${env_create[@]}"} -o none
  fi
}

echo "==> billing-api (rejects any call without the gateway secret header)"
deploy_app billing-api "$REG/billing-api:$TAG" 8000 external \
  "db-url=$DATABASE_URL jwt-secret=$JWT_SECRET gateway-secret=$GATEWAY_SECRET" \
  DATABASE_URL=secretref:db-url JWT_SECRET=secretref:jwt-secret GATEWAY_SECRET=secretref:gateway-secret
API_FQDN="$(az containerapp show -g "$RG" -n billing-api --query properties.configuration.ingress.fqdn -o tsv)"

echo "==> gateway (Kong, external)"
deploy_app gateway "$REG/gateway:$TAG" 8000 external \
  "jwt-secret=$JWT_SECRET gateway-secret=$GATEWAY_SECRET" \
  BILLING_API_URL="https://$API_FQDN" JWT_SECRET=secretref:jwt-secret GATEWAY_SECRET=secretref:gateway-secret

echo "==> mcp-server (external)"
deploy_app mcp-server "$REG/mcp-server:$TAG" 8001 external ""

GW="https://$(az containerapp show -g "$RG" -n gateway --query properties.configuration.ingress.fqdn -o tsv)"
MCP="https://$(az containerapp show -g "$RG" -n mcp-server --query properties.configuration.ingress.fqdn -o tsv)/mcp"

cat <<EOF

Deployment finished.
  API gateway : $GW
  Swagger UI  : $GW/docs
  MCP server  : $MCP
  Billing API : https://$API_FQDN   (direct calls get 403, use the gateway)
  PostgreSQL  : $PG_HOST

For the agent (agent/.env):
  GATEWAY_URL=$GW
  MCP_URL=$MCP
EOF
