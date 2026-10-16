"""MCP server exposing rag's retrieval tools over streamable HTTP.

Tools:
  search(query, collections, k)   hybrid retrieval (optional rerank); returns citable chunk ids
  fetch(id)                       the whole source section for a chunk or section id
  list_collections()              what's indexed, which corpus version, how many sections

Listens on the pod's loopback only (127.0.0.1:8090, path /mcp).
"""

from __future__ import annotations

import os
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from rag.config import Settings
from rag.search import DEFAULT_K, Searcher

INSTRUCTIONS = (
    "Search the user's indexed document collections and cite what you use. "
    "Call search with a focused query (an identifier such as a section number "
    "works well); call fetch with a result's id when the snippet isn't enough. "
    "Cite sources by their id, e.g. [mpep:2143.01#0], and only cite ids returned "
    "by these tools. If the collections don't cover the question, say so."
)


def build_server(searcher: Searcher) -> MCPServer:
    server = MCPServer(name="rag", instructions=INSTRUCTIONS)

    @server.tool(description="Search indexed collections. Returns ranked chunks with citable ids.")
    def search(
        query: str, collections: list[str] | None = None, k: int = DEFAULT_K
    ) -> list[dict[str, Any]]:
        return [r.as_dict() for r in searcher.search(query, collections, k)]

    @server.tool(description="Fetch the full source section for a result id or section id.")
    def fetch(id: str, collection: str | None = None) -> dict[str, Any]:  # noqa: A002
        return searcher.fetch(id, collection)

    @server.tool(description="List indexed collections, corpus versions and sizes.")
    def list_collections() -> list[dict[str, object]]:
        return searcher.list_collections()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    server.custom_route("/health", methods=["GET"])(health)

    return server


def main() -> None:
    searcher = Searcher(Settings.from_env())
    server = build_server(searcher)
    host = os.environ.get("RAG_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("RAG_MCP_PORT", "8090"))
    app = server.streamable_http_app(host=host, stateless_http=True, json_response=True)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
