#!/usr/bin/env bash
# Deletes everything created by deploy.sh (stops all costs).
set -euo pipefail
RG="${RG:-rg-${PREFIX:-se4458bill}}"
az group delete -n "$RG" --yes --no-wait
echo "Deleting resource group $RG (runs in the background)."
