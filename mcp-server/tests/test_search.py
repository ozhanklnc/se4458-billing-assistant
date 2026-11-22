"""Retrieval tests for the billing guide index and the MCP tool.

The three "distinct retrieval queries" required by the assignment are the first
three tests below; the MCP tests call the real tool through an in-process MCP client.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer import BM25Index, DEFAULT_DOC, chunk_markdown, tokenize  # noqa: E402

IDX = BM25Index.from_markdown(DEFAULT_DOC)


def top_sections(query, k=3):
    return [c.id for c, _ in IDX.search(query, k)]


# --- the three retrieval scenarios ------------------------------------------
def test_retrieval_extra_internet_cost():
    assert top_sections("How much does extra internet cost?")[0] == "4.2"


def test_retrieval_partial_payment():
    assert top_sections("Can I pay my bill in parts?")[0] == "6.2"


def test_retrieval_billing_dispute():
    assert top_sections("How do I dispute a wrong charge on my bill?")[0] == "8.1"


def test_retrieval_late_payment_fee():
    assert top_sections("Is there a fee if I pay late?")[0] == "7.1"


# --- index behaviour ----------------------------------------------------------------
def test_chunks_are_subsections_with_parents():
    chunks = chunk_markdown(DEFAULT_DOC.read_text())
    ids = [c.id for c in chunks]
    assert "1.1" in ids and "9.2" in ids
    assert len(ids) == len(set(ids))
    c = next(c for c in chunks if c.id == "4.2")
    assert c.parent.startswith("4.")
    assert "$10" in c.text


def test_unrelated_query_returns_nothing():
    assert IDX.search("zebra volcano spaceship") == []


def test_tokenizer_keeps_decimal_numbers_and_drops_stopwords():
    assert tokenize("The 20.001 GB limit") == ["20.001", "gb", "limit"]


def test_index_roundtrip(tmp_path):
    p = tmp_path / "index.json"
    IDX.save(p)
    loaded = BM25Index.load(p)
    assert [c.id for c, _ in loaded.search("dispute a charge")] == top_sections("dispute a charge")


# --- through MCP ----------------------------------------------------------------------
def test_mcp_tool_listed_and_callable():
    from mcp import Client
    from server import mcp

    async def run():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = [t.name for t in tools.tools]
            assert "search_billing_documentation" in names
            res = await client.call_tool("search_billing_documentation", {"query": "extra data charges"})
            assert not res.is_error
            payload = res.structured_content or json.loads(res.content[0].text)
            first = payload["results"][0]
            assert first["section"] == "4.2"
            assert first["reference"].startswith("Section 4.2")

    asyncio.run(run())
