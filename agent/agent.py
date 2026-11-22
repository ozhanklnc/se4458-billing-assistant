"""Billing support agent: LLM tool selection + tool execution loop.

Flow for each user message
  1. send conversation + tool definitions to the LLM
  2. LLM answers directly or returns tool_calls
  3. the agent executes every tool call (MCP or REST via gateway) and appends results
  4. repeat until the LLM returns a final text answer (max MAX_STEPS rounds)

The LLM never talks to a backend itself and never decides *who* the subscriber is:
the subscriber number comes from the logged-in JWT and is injected here.
"""
from __future__ import annotations

import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable

MAX_STEPS = 6

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

PERIOD_PARAMS = {
    "month": {"type": "integer", "minimum": 1, "maximum": 12, "description": "Bill month 1-12"},
    "year": {"type": "integer", "description": "Bill year, e.g. 2026"},
}

REST_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_bill",
            "description": "Get the signed-in subscriber's bill summary for a month: total, paid amount, "
                           "remaining balance and status. Use for 'what is my bill / how much do I owe'.",
            "parameters": {"type": "object", "properties": PERIOD_PARAMS, "required": ["month", "year"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_bill_detailed",
            "description": "Get the signed-in subscriber's detailed bill for a month: phone minutes, internet "
                           "MB/GB, charge breakdown (extra minute blocks, extra data blocks) and paged usage "
                           "records. Use when the user asks why a bill is high or wants usage details.",
            "parameters": {
                "type": "object",
                "properties": {**PERIOD_PARAMS,
                               "page": {"type": "integer", "minimum": 1, "description": "Usage records page"}},
                "required": ["month", "year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pay_bill",
            "description": "Submit a (simulated) payment for the signed-in subscriber's bill. Partial payments "
                           "are allowed. The application asks the user for explicit confirmation before the "
                           "payment is sent, so call this only when the user wants to pay and the amount is known.",
            "parameters": {
                "type": "object",
                "properties": {**PERIOD_PARAMS,
                               "amount": {"type": "number", "description": "Amount in USD, > 0"}},
                "required": ["month", "year", "amount"],
            },
        },
    },
]


def system_prompt(subscriber_no: str, today: date) -> str:
    return f"""You are the billing support assistant of a mobile provider.
Today is {today.isoformat()}. The signed-in subscriber number is {subscriber_no}.

Tools:
- search_billing_documentation: billing policies (pricing, allowances, cycles, partial payments, late fees, disputes).
- query_bill / query_bill_detailed / pay_bill: the subscriber's live bill data. They always act on the
  signed-in subscriber; you cannot look up other subscribers. If the user asks about another subscriber
  number, say you can only access the signed-in account.

Rules:
- Use tools for facts; never invent amounts, usage or policy rules.
- A month without a year means the most recent such month that is not in the future.
- Questions about why a bill is high need both the detailed bill and the relevant pricing rules.
- When you use the billing guide, cite the section like (Billing Guide §4.2).
- For payments: if the amount is not given, check the remaining balance first and use it. Then call
  pay_bill; the app will ask the user to confirm. If the user declines, do not retry.
- Keep answers short and concrete, with dollar amounts."""


@dataclass
class TraceStep:
    kind: str            # llm | tool
    name: str
    channel: str = ""    # MCP | REST via gateway | LLM
    input: Any = None
    output: Any = None
    ms: int = 0


@dataclass
class TurnResult:
    answer: str
    trace: list[TraceStep] = field(default_factory=list)


ConfirmFn = Callable[[str], bool | Awaitable[bool]]


class BillingAgent:
    def __init__(self, llm, model: str, gateway, docs, confirm: ConfirmFn, today: date | None = None,
                 reasoning_effort: str | None = None):
        self.llm = llm          # AsyncOpenAI-compatible client
        self.model = model
        self.gateway = gateway
        self.docs = docs
        self.confirm = confirm
        self.today = today or date.today()
        self.reasoning_effort = reasoning_effort
        self.tools: list[dict] = []
        self.mcp_tool_names: set[str] = set()
        self.messages: list[dict] = []

    async def start(self):
        mcp_tools = await self.docs.tool_schemas()
        self.mcp_tool_names = {t["function"]["name"] for t in mcp_tools}
        self.tools = mcp_tools + REST_TOOLS
        self.messages = [{"role": "system", "content": system_prompt(self.gateway.subscriber_no, self.today)}]

    # ------------------------------------------------------------------ loop
    async def ask(self, question: str) -> TurnResult:
        self.messages.append({"role": "user", "content": question})
        trace: list[TraceStep] = []

        for _ in range(MAX_STEPS):
            t0 = time.perf_counter()
            extra = {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
            resp = await self.llm.chat.completions.create(
                model=self.model, messages=self.messages, tools=self.tools, tool_choice="auto", **extra,
            )
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            trace.append(TraceStep(
                "llm", "tool selection" if calls else "final answer", "LLM",
                output=[f"{c.function.name}({c.function.arguments})" for c in calls] or "text answer",
                ms=int((time.perf_counter() - t0) * 1000),
            ))
            # keep the assistant message as returned (Gemini needs its thought signatures back)
            self.messages.append(msg.model_dump(exclude_none=True))

            if not calls:
                return TurnResult(msg.content or "", trace)

            for call in calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                t0 = time.perf_counter()
                channel, result = await self.execute(call.function.name, args)
                trace.append(TraceStep("tool", call.function.name, channel, args, result,
                                       int((time.perf_counter() - t0) * 1000)))
                self.messages.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                })

        return TurnResult("Sorry, I could not finish this request. Please try rephrasing it.", trace)

    # ------------------------------------------------------------- execution
    async def execute(self, name: str, args: dict) -> tuple[str, dict]:
        if name in self.mcp_tool_names:
            return "MCP", await self.docs.call(name, args)

        sub = self.gateway.subscriber_no  # identity from the JWT, never from the prompt
        try:
            month, year = int(args["month"]), int(args["year"])
        except (KeyError, TypeError, ValueError):
            return "agent", {"error": "month and year are required integers"}

        if name == "query_bill":
            return "REST via gateway", await self.gateway.query_bill(sub, month, year)
        if name == "query_bill_detailed":
            page = int(args.get("page") or 1)
            return "REST via gateway", await self.gateway.query_bill_detailed(sub, month, year, page)
        if name == "pay_bill":
            return await self._pay(sub, month, year, args.get("amount"))
        return "agent", {"error": f"unknown tool {name}"}

    async def _pay(self, sub: str, month: int, year: int, amount) -> tuple[str, dict]:
        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            return "agent", {"error": "amount must be a number"}
        if amount <= 0:
            return "agent", {"error": "amount must be greater than 0"}

        prompt = (f"Pay ${amount:.2f} for the {MONTHS[month - 1]} {year} bill "
                  f"of subscriber {sub}?")
        ok = self.confirm(prompt)
        if inspect.isawaitable(ok):
            ok = await ok
        if not ok:
            return "agent", {"status": "CANCELLED", "message": "User did not confirm the payment. Nothing was paid."}

        tx = f"AGT-{uuid.uuid4().hex[:16].upper()}"
        result = await self.gateway.pay_bill(sub, month, year, amount, tx)
        result["confirmedByUser"] = True
        return "REST via gateway", result
