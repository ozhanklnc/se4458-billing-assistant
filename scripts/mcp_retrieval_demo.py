"""Runs three distinct retrieval queries against the MCP server over HTTP.

    python scripts/mcp_retrieval_demo.py [MCP_URL]
"""
import asyncio
import sys

from mcp import Client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001/mcp"
QUERIES = [
    "How much does extra internet cost?",
    "Can I pay my bill in parts?",
    "How do I dispute a wrong charge on my bill?",
]


async def main():
    async with Client(URL) as client:
        tools = await client.list_tools()
        for t in tools.tools:
            print(f"tool: {t.name}  schema: {t.input_schema}\n")
        for q in QUERIES:
            res = await client.call_tool("search_billing_documentation", {"query": q, "top_k": 2})
            print(f"query: {q}")
            for r in res.structured_content["results"]:
                print(f"  [{r['score']:6.2f}] {r['reference']}")
                print("          " + r["excerpt"].replace("\n", " ")[:160] + " ...")
            print()


asyncio.run(main())
