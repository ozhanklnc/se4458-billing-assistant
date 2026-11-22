#!/usr/bin/env bash
# Runs every unit test suite. No cloud, database server or LLM key needed.
# Optional: TEST_DATABASE_URL=postgresql+psycopg://... to run the API tests on PostgreSQL.
set -e
cd "$(dirname "$0")/.."
echo "== billing-api";  (cd billing-api && python3 -m pytest -q)
echo "== mcp-server";   (cd mcp-server  && python3 -m pytest -q)
echo "== agent";        (cd agent       && python3 -m pytest -q)
