#!/usr/bin/env bash
# Calls the API through the gateway and prints status codes + bodies.
#   ./scripts/gateway_demo.sh                       (local, http://localhost:8000)
#   GATEWAY_URL=https://gateway.xxx.azurecontainerapps.io ./scripts/gateway_demo.sh
set -u
GW="${GATEWAY_URL:-http://localhost:8000}"
show() { echo; echo "### $1"; shift; curl -s -i "$@" | sed -n '1p;/^[Xx]-[Rr]ate[Ll]imit-[Rr]emaining-[Mm]inute/p;/^[Xx]-[Rr]equest-[Ii][Dd]/p;$p'; echo; }

show "1) public route: Query Bill (no token)" \
  "$GW/api/v1/bills?subscriberNo=5551001&month=10&year=2026"

show "2) protected route WITHOUT token -> 401 from the gateway" \
  "$GW/api/v1/bills/detailed?subscriberNo=5551001&month=10&year=2026"

show "3) protected route with a forged token -> 401 from the gateway" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJiaWxsaW5nLWFwaSJ9.bad" \
  "$GW/api/v1/bills/detailed?subscriberNo=5551001&month=10&year=2026"

TOKEN=$(curl -s -X POST "$GW/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"deniz","password":"Deniz!2026"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["accessToken"])')
echo; echo "### login as deniz (subscriber 5551001) -> token ${TOKEN:0:25}..."

show "4) protected route with token -> 200" -H "Authorization: Bearer $TOKEN" \
  "$GW/api/v1/bills/detailed?subscriberNo=5551001&month=10&year=2026&page=1&pageSize=2"

show "5) same token, someone else's subscriber number -> 403 from the API" -H "Authorization: Bearer $TOKEN" \
  "$GW/api/v1/bills/detailed?subscriberNo=5551002&month=10&year=2026"

show "6) unknown route -> 404 from the gateway" "$GW/api/v2/bills"
