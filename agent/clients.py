"""Thin clients the agent uses to execute tool calls.

GatewayClient -> REST calls, always to the API gateway URL (never to the API directly).
DocsClient    -> MCP client session to the billing-docs MCP server.
"""
from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import Client


class GatewayError(Exception):
    pass


class GatewayClient:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None
        self.subscriber_no: str | None = None
        self.username: str | None = None
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def close(self):
        await self._http.aclose()

    async def login(self, username: str, password: str) -> dict:
        r = await self._http.post("/api/v1/auth/login", json={"username": username, "password": password})
        if r.status_code != 200:
            raise GatewayError(f"Login failed ({r.status_code}): {r.text}")
        data = r.json()
        self.token = data["accessToken"]
        self.subscriber_no = data.get("subscriberNo")
        self.username = username
        return data

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @staticmethod
    def _result(r: httpx.Response) -> dict[str, Any]:
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text}
        # Error bodies are passed back to the LLM as-is so it can explain them.
        return {"httpStatus": r.status_code, "body": body}

    async def query_bill(self, subscriber_no: str, month: int, year: int) -> dict:
        r = await self._http.get(
            "/api/v1/bills", params={"subscriberNo": subscriber_no, "month": month, "year": year}
        )
        return self._result(r)

    async def query_bill_detailed(
        self, subscriber_no: str, month: int, year: int, page: int = 1, page_size: int = 10
    ) -> dict:
        r = await self._http.get(
            "/api/v1/bills/detailed",
            params={"subscriberNo": subscriber_no, "month": month, "year": year,
                    "page": page, "pageSize": page_size},
            headers=self._auth(),
        )
        return self._result(r)

    async def pay_bill(
        self, subscriber_no: str, month: int, year: int, amount: float, transaction_id: str
    ) -> dict:
        r = await self._http.post(
            "/api/v1/payments",
            json={"subscriberNo": subscriber_no, "month": month, "year": year,
                  "amount": amount, "transactionId": transaction_id},
            headers=self._auth(),
        )
        return self._result(r)


class DocsClient:
    """Keeps one MCP session open for the whole chat."""

    def __init__(self, url: str):
        self.url = url
        self._stack = AsyncExitStack()
        self._client: Client | None = None

    async def __aenter__(self):
        self._client = await self._stack.enter_async_context(Client(self.url))
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()

    async def tool_schemas(self) -> list[dict]:
        """MCP tool list converted to OpenAI-style function definitions."""
        listed = await self._client.list_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": (t.description or "").strip(),
                    "parameters": t.input_schema,
                },
            }
            for t in listed.tools
        ]

    async def call(self, name: str, arguments: dict) -> dict:
        res = await self._client.call_tool(name, arguments)
        if res.is_error:
            text = " ".join(getattr(c, "text", "") for c in res.content)
            return {"error": text or "MCP tool error"}
        if res.structured_content is not None:
            return res.structured_content
        return {"text": " ".join(getattr(c, "text", "") for c in res.content)}
