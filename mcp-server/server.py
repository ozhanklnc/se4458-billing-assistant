"""MCP server exposing the billing guide search tool.

Runs with the official MCP Python SDK (mcp>=2, MCPServer) over Streamable HTTP:

    python server.py                       # http://0.0.0.0:8001/mcp
    MCP_TRANSPORT=stdio python server.py   # for MCP Inspector / desktop clients
"""
import logging
import os

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from indexer import load_or_build

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("billing-mcp")

# Index is built (or loaded from index.json) once, when the process starts.
INDEX = load_or_build()
log.info("Billing guide index ready: %d chunks from %s", INDEX.n, INDEX.source)

mcp = MCPServer(
    name="billing-docs",
    instructions=(
        "Search the Mobile Provider Billing Guide (allowances, pricing, billing cycle, "
        "partial payments, late payments, disputes). Returns excerpts with section numbers."
    ),
)


class Excerpt(BaseModel):
    section: str = Field(description="Section number, e.g. '4.2'")
    title: str
    reference: str = Field(description="Human readable reference to cite in answers")
    parent_section: str
    score: float
    excerpt: str


class SearchResult(BaseModel):
    query: str
    document: str
    results: list[Excerpt]


@mcp.tool()
def search_billing_documentation(query: str, top_k: int = 3) -> SearchResult:
    """Search the mobile provider billing guide.

    Use for policy questions: what something costs, allowances, how the bill is
    calculated, rounding, billing cycle and due dates, partial payments, late fees,
    disputes. Does NOT contain any subscriber's personal bill or usage.

    Args:
        query: natural language search text, e.g. "extra data charges"
        top_k: number of excerpts to return (1-5)
    """
    top_k = max(1, min(int(top_k), 5))
    hits = INDEX.search(query, top_k)
    log.info("search %r -> %s", query, [c.id for c, _ in hits])
    return SearchResult(
        query=query,
        document=INDEX.source,
        results=[
            Excerpt(
                section=c.id,
                title=c.title,
                reference=c.reference,
                parent_section=c.parent,
                score=round(s, 3),
                excerpt=c.text,
            )
            for c, s in hits
        ],
    )


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run(
            "streamable-http",
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8001")),
            stateless_http=True,
            json_response=True,
        )
