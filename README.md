# AI Billing Support Assistant — SE4458 Midterm (Group 2)

A conversational billing assistant for mobile subscribers. The agent uses an LLM with real
tool/function calling to decide, per question, whether to search the billing guide over **MCP**,
call the **Billing REST API through the API gateway**, or both.

| Component | Technology | Where it runs |
|---|---|---|
| Billing REST API | Python 3.12, FastAPI, SQLAlchemy 2 | Azure Container Apps (rejects calls that bypass the gateway) |
| Server database | PostgreSQL 16 | Azure Database for PostgreSQL – Flexible Server (Burstable) |
| API Gateway | Kong 3.9 (DB-less, declarative config) | Azure Container Apps (public) |
| MCP server | Official MCP Python SDK (`mcp` 2.x, `MCPServer`), Streamable HTTP | Azure Container Apps (public) |
| AI agent | Python, OpenAI-compatible chat completions with tools, MCP client | CLI on the user's machine |
| LLM | Gemini Flash via the OpenAI-compatible endpoint (any OpenAI-compatible model works) | Google AI Studio |

> **Demo video:** [docs/video/demo.mp4](docs/video/demo.mp4) (3:37, Turkish narration). It shows the
> README, Swagger on Azure, the gateway checks, the agent scenarios (MCP-only, API-only, combined,
> confirmed payment) and the unit test run.

> **Deployed on Azure**
> - API Gateway: https://gateway.yellowsmoke-193d061f.germanywestcentral.azurecontainerapps.io
> - Swagger UI (through the gateway): https://gateway.yellowsmoke-193d061f.germanywestcentral.azurecontainerapps.io/docs
> - MCP server: https://mcp-server.yellowsmoke-193d061f.germanywestcentral.azurecontainerapps.io/mcp

---

## 1. Architecture

```mermaid
flowchart TB
    U[User / CLI chat] -->|question| A[AI Agent orchestrator<br/>LLM client + tool execution]
    A <-->|messages + tool definitions / tool_calls| L[LLM<br/>tool selection + answer]
    A -->|MCP tool call| MC[MCP client]
    MC <-->|Streamable HTTP| MS[MCP server<br/>search_billing_documentation]
    MS --> IDX[(BM25 index of<br/>Mobile_Provider_Billing_Guide.md)]
    A -->|REST + JWT| GW[Kong API Gateway<br/>/api/v1/* routes, JWT, rate limits]
    GW --> API[Billing REST API]
    API --> DB[(PostgreSQL)]
```

How one question is handled (`agent/agent.py`):

1. The agent sends the conversation plus four tool definitions to the LLM:
   `search_billing_documentation` (taken from the MCP server's `list_tools`), `query_bill`,
   `query_bill_detailed`, `pay_bill`.
2. The LLM either answers or returns `tool_calls`. Routing is done only by the LLM; the agent has no
   keyword rules.
3. The agent executes each call itself: MCP calls go to the MCP server, REST calls go to the gateway.
   The LLM never talks to a backend.
4. Results are appended as `tool` messages and the LLM is called again, until it returns the final
   answer (max 6 rounds). The answer cites guide sections, e.g. *(Billing Guide §4.2)*.

The MCP path and the gateway path are separate, as required.

## 2. Repository layout

```
billing-api/          REST API (FastAPI) + unit tests + Dockerfile
  app/pricing.py      bill calculation rules (pure functions)
  app/services.py     business logic (usage, calculate, query, pay)
  app/security.py     JWT, roles, ownership check
  app/seed.py         creates tables and demo data
mcp-server/           MCP server + indexer + billing guide + tests
  docs/Mobile_Provider_Billing_Guide.md
gateway/kong/         Kong declarative config template, entrypoint, Dockerfile
agent/                agent loop, MCP/gateway clients, CLI, tests
db/schema.sql         PostgreSQL DDL (generated from the models)
docs/                 ER diagram, openapi.json, screenshots
infra/azure/          deploy.sh / teardown.sh
scripts/              run_tests.sh, gateway_demo.sh, mcp_retrieval_demo.py
docker-compose.yml    local stack (db + api + mcp + gateway)
```

## 3. Assumptions and design decisions

**Billing rules**
- Phone: first 1,000 minutes free, then $10 per *started* 1,000-minute block above 1,000.
  1,001 min → $10, 2,000 min → $10, 2,001 min → $20.
- Internet: the $50 package is charged every month, even with 0 MB used. Above 20,000 MB,
  $10 per *started* 10,000 MB block. 20,001 MB → $60, 35,000 MB → $70.
- 1 GB = 1,000 MB (assignment definition). Money is `numeric(10,2)`, currency USD. There is no
  fractional rounding because all prices are whole blocks.
- Bill total = phone charge + internet charge. Minimum bill is $50.

**Operations**
- *Add Usage* follows the spec literally: one call adds 10 minutes (`PHONE`) or 1 MB (`INTERNET`)
  to the given month. Demo data is loaded by `app/seed.py` as daily aggregate rows, so a 35 GB month
  doesn't need 35,000 API calls.
- *Calculate Bill* creates the bill for (subscriber, month, year) or recalculates it. Recalculation
  **keeps all payments** (`paid_amount` is never reset) and updates the status. There is one bill
  per subscriber per month (unique constraint).
- Future periods are rejected (`422 INVALID_PERIOD`) for Add Usage and Calculate Bill.
- *Pay Bill* is simulated (no card data). Partial payments are allowed. Rejected cases:
  duplicate `transactionId` → `409 DUPLICATE_TRANSACTION` (balance unchanged); amount above the
  remaining balance → `422 AMOUNT_EXCEEDS_BALANCE`; bill already paid → `409 BILL_ALREADY_PAID`;
  bill not calculated yet → `404 BILL_NOT_FOUND`. The bill row is locked (`SELECT ... FOR UPDATE`)
  during payment, and `transaction_id` has a unique constraint, which also covers concurrent retries.
- Status values are `UNPAID`, `PARTIALLY_PAID` and `PAID`.

**Identity and authorization**
- JWT (HS256) is issued by `POST /api/v1/auth/login`. Claims: `iss=billing-api`, `sub`, `role`,
  `subscriberNo`, `exp` (60 min). Passwords are stored as bcrypt hashes.
- Roles: `SUBSCRIBER` (bound to one subscriber number) and `ADMIN`. Add Usage and Calculate Bill
  are back-office operations and need `ADMIN`. Query Bill Detailed and Pay Bill need a token whose
  `subscriberNo` matches the request (or `ADMIN`), otherwise `403`.
- Query Bill has no authentication, because the spec table says "Authentication: NO". It only
  returns the summary (total, paid, remaining, status).
- The agent never takes a subscriber number from the prompt. The number comes from the logged-in
  token and is injected by the agent when it executes a tool. The LLM tool schemas don't even have
  a subscriber parameter, and the API enforces ownership again as a second line of defense.
- Payments need explicit confirmation. When the LLM calls `pay_bill`, the agent stops, shows
  *"Pay $X for the October 2026 bill of subscriber N? [yes/no]"* and only calls the API after a
  "yes". A "no" is returned to the LLM as `CANCELLED`. Each confirmed payment gets a new
  transaction ID (`AGT-…`).
- The gateway validates the JWT (signature, `iss`, `exp`) before a protected request reaches the
  API. The API validates it again.
- Gateway-only access: Kong adds an `X-Gateway-Secret` header (shared secret, stored as a
  Container Apps secret) to every request. The API rejects any request without it with
  `403 DIRECT_ACCESS_FORBIDDEN`, so calling the API URL directly does not work.

**API errors**
All API errors use one format:
```json
{ "status": "ERROR", "code": "BILL_NOT_FOUND", "message": "No bill calculated for subscriber 5551001 for 2026-01" }
```
Codes: `VALIDATION_ERROR` (422), `INVALID_PERIOD` (422), `AMOUNT_EXCEEDS_BALANCE` (422),
`UNAUTHORIZED` / `INVALID_CREDENTIALS` (401), `FORBIDDEN` (403), `SUBSCRIBER_NOT_FOUND` /
`BILL_NOT_FOUND` (404), `DUPLICATE_TRANSACTION` / `BILL_ALREADY_PAID` (409).

**Policy interpretation**
The billing guide is fictitious and was written to match the API rules exactly (sections 3–6).
Late fees, service restriction and disputes (sections 7–8) are documentation only; no API implements them.

**Deployment**
Everything runs on Azure (section 9). The billing API only accepts requests carrying the
gateway's secret header, so the gateway is the only working way into the REST API. The CLI agent runs on the user's machine, which the
assignment allows ("a simple command-line ... chat interface is sufficient").

## 4. Data model

![ER diagram](docs/er-diagram.png)

`subscribers` 1–N `usage_records`, `subscribers` 1–N `bills` (one per month), `bills` 1–N
`payments`, `subscribers` 1–0..1 `app_users`. DDL: [`db/schema.sql`](db/schema.sql).
SQLite is not used by the application; it is only the default for the unit tests (section 10).

## 5. REST API (v1)

Swagger UI: `/docs` (through the gateway). Static spec: [`docs/openapi.json`](docs/openapi.json).

| Operation | Method & route | Auth | Paging | Body / query |
|---|---|---|---|---|
| Login | `POST /api/v1/auth/login` | – | – | `username, password` |
| Add Usage | `POST /api/v1/usage` | JWT, ADMIN | No | `subscriberNo, month, year, usageType (PHONE\|INTERNET)` |
| Calculate Bill | `POST /api/v1/bills/calculate` | JWT, ADMIN | No | `subscriberNo, month, year` |
| Query Bill | `GET /api/v1/bills` | **No** | No | `?subscriberNo&month&year` |
| Query Bill Detailed | `GET /api/v1/bills/detailed` | JWT, owner/ADMIN | **Yes** (`page`, `pageSize` ≤ 100) | `?subscriberNo&month&year&page&pageSize` |
| Pay Bill | `POST /api/v1/payments` | JWT, owner/ADMIN | No | `subscriberNo, month, year, amount, transactionId` |

**Versioning.** Every route lives under `/api/v1`. A breaking change would be a new
`/api/v2` router in the API and a new service/route set in Kong, while v1 keeps running.

Example `GET /api/v1/bills/detailed?subscriberNo=5551001&month=10&year=2026&pageSize=2`:
```json
{
  "subscriberNo": "5551001", "month": 10, "year": 2026,
  "billTotal": "80.00", "paidAmount": "0.00", "remainingBalance": "80.00",
  "currency": "USD", "status": "UNPAID",
  "phoneMinutes": 1450, "internetMb": 35000, "internetGb": "35.000",
  "charges": [
    {"item": "Phone - included minutes", "quantity": "1000", "unit": "MIN", "amount": "0.00", "note": "First 1,000 minutes are free"},
    {"item": "Phone - extra minute blocks", "quantity": "1", "unit": "BLOCK", "amount": "10.00", "note": "$10 per started 1,000-minute block above 1,000 minutes"},
    {"item": "Internet - base package", "quantity": "1", "unit": "PACKAGE", "amount": "50.00", "note": "Covers up to 20 GB (20,000 MB)"},
    {"item": "Internet - extra data blocks", "quantity": "2", "unit": "BLOCK", "amount": "20.00", "note": "$10 per started 10 GB block above 20 GB"}
  ],
  "usageRecords": [
    {"id": 49, "usageType": "PHONE", "quantity": 140, "unit": "MIN", "recordedAt": "2026-10-01T18:00:00Z"},
    {"id": 59, "usageType": "INTERNET", "quantity": 2500, "unit": "MB", "recordedAt": "2026-10-01T21:00:00Z"}
  ],
  "paging": {"page": 1, "pageSize": 2, "totalItems": 24, "totalPages": 12}
}
```

## 6. API Gateway (Kong)

Config: [`gateway/kong/kong.yml.tmpl`](gateway/kong/kong.yml.tmpl). Kong runs in DB-less mode. The
upstream URL and the JWT secret are injected from environment variables at start-up
(`entrypoint.sh`), so the same file is used locally and on Azure. All REST traffic from the
agent goes through the gateway (`GATEWAY_URL`).

| Gateway route (public) | Methods | Upstream | Plugins |
|---|---|---|---|
| `/api/v1/auth/login` | POST | billing-api `/api/v1/auth/login` | rate-limiting 10/min per IP |
| `/api/v1/bills` (exact) | GET | billing-api `/api/v1/bills` | rate-limiting 30/min, 300/h per IP |
| `/api/v1/bills/detailed` | GET | billing-api `/api/v1/bills/detailed` | **jwt**, rate-limiting 60/min per token |
| `/api/v1/payments` | POST | billing-api `/api/v1/payments` | **jwt**, rate-limiting 60/min per token |
| `/api/v1/bills/calculate` | POST | billing-api `/api/v1/bills/calculate` | **jwt**, rate-limiting 60/min per token |
| `/api/v1/usage` | POST | billing-api `/api/v1/usage` | **jwt**, rate-limiting 60/min per token |
| `/docs`, `/openapi.json`, `/health` | GET | billing-api | – |

Global plugins: `request-transformer` (adds the `X-Gateway-Secret` header the API requires),
`correlation-id` (an `X-Request-ID` on every response) and `cors`. The Group 2 spec
defines no rate limit, so the limits above are my own protective defaults. Limits on protected
routes are keyed by the caller's token (identity), not only the client IP.

JWT check at the gateway: Kong looks up the credential by the `iss` claim (`billing-api`),
verifies the HS256 signature with the shared secret, and checks `exp`.

Error responses produced by the gateway itself:
```
GET /api/v1/bills/detailed?...            (no token)
HTTP/1.1 401 Unauthorized
{"message":"Unauthorized"}

GET /api/v1/bills/detailed?...            (tampered token)
HTTP/1.1 401 Unauthorized
{"message":"Invalid signature"}

61st call within a minute on a protected route
HTTP/1.1 429 Too Many Requests
{"message":"API rate limit exceeded"}
```
`scripts/gateway_demo.sh` shows a public route, protected-route 401s, a successful call with a
token, a 403 for another subscriber's data, and a 404 for an unknown route.

## 7. MCP server and indexing

- Tool name: `search_billing_documentation`.
- Transport: Streamable HTTP at `/mcp` (stateless, JSON responses). Set `MCP_TRANSPORT=stdio` for
  MCP Inspector or desktop clients.
- Input schema (as returned by `list_tools`):
  ```json
  {"type":"object","properties":{"query":{"type":"string"},"top_k":{"type":"integer","default":3}},"required":["query"]}
  ```
- Output: `{query, document, results:[{section, title, reference, parent_section, score, excerpt}]}`,
  e.g. `reference: "Section 4.2 – Extra data charges"`.

**Indexing approach** ([`mcp-server/indexer.py`](mcp-server/indexer.py))
1. *Chunking*: one chunk per `###` subsection of the guide (29 chunks). Each chunk keeps its
   section number, its title and its parent section, so every result can be cited.
2. *Tokens*: lower-case, stop words removed, simple suffix stemming. The title is counted twice
   because headings are the most informative text.
3. *Ranking*: Okapi BM25 (k1 = 1.5, b = 0.75). This is full-text search; no embeddings are used,
   which the assignment allows.
4. *Query expansion*: a small synonym table (internet↔data, cost→price/charge/fee,
   late↔overdue, extra↔additional …) at half weight, so user wording matches the guide's wording.
5. The index is built **once**: at Docker image build time (`RUN python indexer.py` →
   `index.json`), and the server only loads it at start-up. If `index.json` is missing or older than the guide, it is
   rebuilt once at start-up. Nothing is re-indexed per question.

**Three retrieval tests** (`mcp-server/tests/test_search.py`, and live over HTTP with
`python scripts/mcp_retrieval_demo.py <MCP_URL>`):

| Query | Top result |
|---|---|
| How much does extra internet cost? | Section 4.2 – Extra data charges |
| Can I pay my bill in parts? | Section 6.2 – Partial payments |
| How do I dispute a wrong charge on my bill? | Section 8.1 – How to dispute a charge |

## 8. AI agent

Run: `cd agent && python cli.py` (interactive) or `python cli.py -q "What is my October bill?"`.

| Example | Tools the LLM selects |
|---|---|
| How much does extra internet cost? | `search_billing_documentation` (MCP only) |
| What is my October bill? | `query_bill` (REST only) |
| Why is my October bill higher? | `query_bill_detailed` + `search_billing_documentation` (combined) |
| Pay my bill | `query_bill` → `pay_bill` → **confirmation prompt** → Pay Bill API |

Each turn prints a tool trace (LLM decision, tool name, channel, input, result, final answer) and
appends it to `agent/logs/trace-<timestamp>.jsonl`. Sample trace:

```
you> Why is my October bill higher?
  ── tool trace ─────────────────────────────────────────────
  [LLM] tool selection: ["query_bill_detailed({"month": 10, "year": 2026})",
                         "search_billing_documentation({"query": "extra data charges"})"]
  [1] query_bill_detailed  via REST via gateway
      input : {"month": 10, "year": 2026}
      result: {"httpStatus": 200, "body": {"billTotal": "80.00", "phoneMinutes": 1450, "internetGb": "35.000", ...}}
  [2] search_billing_documentation  via MCP
      input : {"query": "extra data charges"}
      result: {"results": [{"section": "4.2", "reference": "Section 4.2 – Extra data charges", ...}]}
  [LLM] final answer: text answer
assistant> Your October bill is $80. You used 35 GB of data, 15 GB over the 20 GB allowance,
which starts two extra 10 GB blocks ($20) on top of the $50 package (Billing Guide §4.2) ...
```

**LLM and cost.** The agent uses the OpenAI Python SDK against any OpenAI-compatible endpoint
(`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` in `agent/.env`). The default is `gemini-3.5-flash-lite` (with `reasoning_effort=low` to keep latency down) through
Google's OpenAI-compatible endpoint. The free tier of Google AI Studio is enough for the demo, so
the LLM cost for this project was $0. A question uses 2–3 LLM calls of a few thousand tokens each;
on a small paid model (e.g. `gpt-4o-mini`) that is a fraction of a cent per question. The unit tests
use a scripted fake LLM, so they need no key and cost nothing.

## 9. Running it

### 9.1 Local (Docker)
```bash
docker compose up --build            # postgres, billing-api, mcp-server, kong gateway
# gateway  http://localhost:8000   (Swagger: http://localhost:8000/docs)
# mcp      http://localhost:8001/mcp

cd agent
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env                 # put your LLM_API_KEY in it
python cli.py                        # log in as deniz / Deniz!2026
```

### 9.2 Azure
Prerequisites: Azure subscription (Azure for Students works), `az login`, Docker running.
```bash
./infra/azure/deploy.sh              # ~10-15 min, prints the gateway and MCP URLs
# then put GATEWAY_URL and MCP_URL into agent/.env and run the CLI as above
./infra/azure/teardown.sh            # delete everything afterwards
```
The script creates: resource group, PostgreSQL Flexible Server (Burstable tier, PG 16, Azure-only
firewall; it tries the region/SKU combinations an Azure for Students subscription allows, because
not every region offers PostgreSQL there), Azure Container Registry (Basic), a Container Apps
environment and three apps (`billing-api`, `gateway`, `mcp-server`). Secrets (DB password, JWT
secret) are generated and stored as Container Apps secrets. The API container creates the tables
and loads the demo data on first start.

Cost: Container Apps on the consumption plan stays within the monthly free grant at this scale.
PostgreSQL on the Burstable tier is covered by the Azure for Students credit.
ACR Basic costs a few cents per day. Run `teardown.sh` after grading.

## 10. Unit tests

```bash
pip install -r billing-api/requirements.txt -r mcp-server/requirements.txt -r agent/requirements.txt
./scripts/run_tests.sh
```
- No cloud, no running services and no LLM key are needed. API tests use an in-memory database by
  default; to run the same tests against PostgreSQL:
  `TEST_DATABASE_URL=postgresql+psycopg://billing:billing@localhost:5432/billing_test ./scripts/run_tests.sh`
- `billing-api/tests` (48 tests): pricing rules (block boundaries), and for every operation at least
  one success test and several failure/edge tests: missing token, wrong role, another subscriber's
  data, direct calls without the gateway header, validation errors, future period, unknown subscriber, bill not found, duplicate transaction,
  overpayment, paying a paid bill, recalculation keeping payments, paging, expired token.
- `mcp-server/tests` (9 tests): the retrieval queries, chunking, index save/load, and a call through a
  real MCP client.
- `agent/tests` (8 tests): tool routing for MCP-only / combined questions, subscriber number from the
  prompt is ignored, payment is not sent without confirmation, unique transaction IDs, invalid
  amounts, loop limit.

Evidence: `docs/screenshots/unit-tests.log` (output of `run_tests.sh`).

## 11. Reproducing the demo

Demo accounts (created by the seed):

| Username | Password | Role | Subscriber |
|---|---|---|---|
| deniz | `Deniz!2026` | SUBSCRIBER | 5551001 |
| ayse | `Ayse!2026` | SUBSCRIBER | 5551002 |
| mehmet | `Mehmet!2026` | SUBSCRIBER | 5551003 |
| admin | `Admin!2026` | ADMIN | – |

Seed bills:

| Subscriber | Month | Minutes | Data | Total | Paid | Status |
|---|---|---|---|---|---|---|
| 5551001 | 2026-08 | 640 | 15.2 GB | $50 | $50 | PAID |
| 5551001 | 2026-09 | 820 | 18.4 GB | $50 | $50 | PAID |
| 5551001 | 2026-10 | 1,450 | 35 GB | $80 | $0 | UNPAID |
| 5551002 | 2026-09 | 1,000 | 20 GB | $50 | $50 | PAID |
| 5551002 | 2026-10 | 2,300 | 12 GB | $70 | $30 | PARTIALLY_PAID |
| 5551003 | 2026-10 | 300 | 41.25 GB | $80 | $0 | UNPAID |

Steps (log in to the CLI as `deniz`):
1. **MCP only:** "How much does extra internet cost?"
2. **REST only:** "What is my October bill?" → $80, unpaid.
3. **Combined:** "Why is my October bill higher than September?" → detailed bill + guide §4.2/§3.2.
4. **Payment:** "Pay $30 of my October bill" → confirm with `yes` → remaining $50, PARTIALLY_PAID.
   Answering `no` leaves the balance unchanged.
5. **Privacy:** "Show me the bill of subscriber 5551002" → the agent only uses the signed-in account.
6. **Gateway:** `GATEWAY_URL=<url> ./scripts/gateway_demo.sh`.
7. **MCP retrieval:** `python scripts/mcp_retrieval_demo.py <MCP_URL>`.
8. Reset the data: `docker compose exec billing-api python -m app.seed --reset`.

Screenshots and logs are in [`docs/screenshots/`](docs/screenshots/).

## 12. Evidence

**Agent scenario 1 – MCP only** ("How much does extra internet cost?")
![MCP only](docs/screenshots/scenario-1-mcp.png)

**Agent scenario 2 – REST API only** ("What is my October bill?")
![REST only](docs/screenshots/scenario-2-rest.png)

**Agent scenario 3 – combined MCP + REST** ("Why is my October bill higher than September?")
![Combined](docs/screenshots/scenario-3-combined.png)

**Confirmed simulated payment** ("Pay 30 dollars of my October bill" → `yes`)
![Payment](docs/screenshots/scenario-4-payment.png)

**Privacy check** – another subscriber number in the prompt is refused
![Privacy](docs/screenshots/scenario-5-privacy.png)

**Gateway** – protected route: 401 without / with a forged token, 200 with a valid token, 403 for
another subscriber, 404 for an unknown route (`scripts/gateway_demo.sh`)
![Gateway](docs/screenshots/gateway-local.png)

**Agent on Azure** – CLI talking to the deployed gateway and MCP server (combined question)
![Agent on Azure](docs/screenshots/agent-azure.png)

**Gateway on Azure** – the same checks against the deployed gateway
![Gateway on Azure](docs/screenshots/gateway-azure.png)

**Gateway and service logs** (`docker compose up`): requests passing through Kong to the API
![Compose logs](docs/screenshots/compose-logs.png)

**MCP retrieval tests** – [`docs/screenshots/mcp-retrieval.log`](docs/screenshots/mcp-retrieval.log)
· **Unit tests** – [`docs/screenshots/unit-tests.log`](docs/screenshots/unit-tests.log)
