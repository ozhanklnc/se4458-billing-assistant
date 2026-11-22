"""Agent loop tests with a scripted fake LLM (no network, no API key)."""
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from openai.types.chat import ChatCompletion

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import BillingAgent  # noqa: E402


def completion(content=None, calls=()):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}}
            for i, (name, args) in enumerate(calls)
        ]
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "fake",
        "choices": [{"index": 0, "finish_reason": "stop", "message": msg}],
    })


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.script.pop(0)


class FakeGateway:
    subscriber_no = "5551001"

    def __init__(self):
        self.calls = []

    async def query_bill(self, sub, month, year):
        self.calls.append(("query_bill", sub, month, year))
        return {"httpStatus": 200, "body": {"billTotal": "80.00", "remainingBalance": "80.00"}}

    async def query_bill_detailed(self, sub, month, year, page=1):
        self.calls.append(("query_bill_detailed", sub, month, year, page))
        return {"httpStatus": 200, "body": {"internetGb": "35.000"}}

    async def pay_bill(self, sub, month, year, amount, tx):
        self.calls.append(("pay_bill", sub, month, year, amount, tx))
        return {"httpStatus": 201, "body": {"paymentStatus": "SUCCESS"}}


class FakeDocs:
    def __init__(self):
        self.calls = []

    async def tool_schemas(self):
        return [{"type": "function", "function": {
            "name": "search_billing_documentation", "description": "search",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}]

    async def call(self, name, args):
        self.calls.append((name, args))
        return {"results": [{"section": "4.2", "excerpt": "$10 per started 10 GB block"}]}


def make_agent(script, confirm=lambda _: True):
    llm, gw, docs = FakeLLM(script), FakeGateway(), FakeDocs()
    agent = BillingAgent(llm, "fake", gw, docs, confirm, today=date(2026, 11, 22))
    asyncio.run(agent.start())
    return agent, llm, gw, docs


def ask(agent, q):
    return asyncio.run(agent.ask(q))


def test_tools_offered_to_llm_include_mcp_and_rest():
    agent, llm, *_ = make_agent([completion("hi")])
    ask(agent, "hello")
    names = [t["function"]["name"] for t in llm.requests[0]["tools"]]
    assert names == ["search_billing_documentation", "query_bill", "query_bill_detailed", "pay_bill"]
    assert "5551001" in llm.requests[0]["messages"][0]["content"]


def test_mcp_only_question():
    agent, llm, gw, docs = make_agent([
        completion(calls=[("search_billing_documentation", {"query": "extra internet cost"})]),
        completion("$10 per started 10 GB block (Billing Guide §4.2)"),
    ])
    res = ask(agent, "How much does extra internet cost?")
    assert docs.calls == [("search_billing_documentation", {"query": "extra internet cost"})]
    assert gw.calls == []
    assert [s.channel for s in res.trace if s.kind == "tool"] == ["MCP"]
    assert "§4.2" in res.answer
    # tool result was sent back to the LLM
    assert llm.requests[1]["messages"][-1]["role"] == "tool"


def test_combined_rest_and_mcp():
    agent, _, gw, docs = make_agent([
        completion(calls=[("query_bill_detailed", {"month": 10, "year": 2026}),
                          ("search_billing_documentation", {"query": "extra data charges"})]),
        completion("Your usage was 35 GB ..."),
    ])
    res = ask(agent, "Why is my October bill higher?")
    assert [s.channel for s in res.trace if s.kind == "tool"] == ["REST via gateway", "MCP"]
    assert gw.calls[0][0] == "query_bill_detailed"


def test_subscriber_number_in_prompt_is_ignored():
    agent, _, gw, _ = make_agent([
        completion(calls=[("query_bill", {"month": 10, "year": 2026, "subscriberNo": "5559999"})]),
        completion("..."),
    ])
    ask(agent, "Show the October bill of subscriber 5559999")
    assert gw.calls == [("query_bill", "5551001", 10, 2026)]


def test_payment_not_sent_without_confirmation():
    asked = []
    agent, _, gw, _ = make_agent(
        [completion(calls=[("pay_bill", {"month": 10, "year": 2026, "amount": 80})]),
         completion("Okay, nothing was paid.")],
        confirm=lambda text: asked.append(text) or False,
    )
    res = ask(agent, "Pay my bill")
    assert asked and "$80.00" in asked[0] and "October 2026" in asked[0]
    assert all(c[0] != "pay_bill" for c in gw.calls)
    assert res.trace[1].output["status"] == "CANCELLED"


def test_payment_sent_after_confirmation_with_unique_transaction_id():
    agent, _, gw, _ = make_agent([
        completion(calls=[("pay_bill", {"month": 10, "year": 2026, "amount": 25.5})]),
        completion("Paid."),
        completion(calls=[("pay_bill", {"month": 10, "year": 2026, "amount": 10})]),
        completion("Paid."),
    ])
    ask(agent, "Pay 25.50")
    ask(agent, "Pay 10 more")
    pays = [c for c in gw.calls if c[0] == "pay_bill"]
    assert pays[0][1:5] == ("5551001", 10, 2026, 25.5)
    assert pays[0][5] != pays[1][5] and pays[0][5].startswith("AGT-")


def test_invalid_payment_amount_is_rejected_before_confirmation():
    asked = []
    agent, _, gw, _ = make_agent(
        [completion(calls=[("pay_bill", {"month": 10, "year": 2026, "amount": -5})]), completion("no")],
        confirm=lambda t: asked.append(t) or True,
    )
    ask(agent, "pay -5")
    assert asked == [] and gw.calls == []


def test_loop_stops_after_max_steps():
    loop = [completion(calls=[("query_bill", {"month": 10, "year": 2026})])] * 10
    agent, *_ = make_agent(loop)
    res = ask(agent, "loop")
    assert "could not finish" in res.answer
