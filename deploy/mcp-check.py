"""End-to-end check through the MCP server, the way an MCP client sees it.

Run inside the pod (deploy/mcp-check.sh does this): lists the tools from
http://127.0.0.1:8090/mcp, then for each question lets the chat model (through
Llama Stack) call those tools over MCP and answer with citations. Prints the
answer, the cited ids, whether each was returned by a tool, and timings.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from rag.answers import CITATION, FINAL_NUDGE, MAX_ROUNDS, SYSTEM

MCP_URL = os.environ.get("RAG_MCP_URL", "http://127.0.0.1:8090/mcp")
STACK_URL = os.environ.get("RAG_STACK_URL", "http://127.0.0.1:8321/v1")


def _tools(listed: Any) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.input_schema,
            },
        }
        for t in listed.tools
    ]


def _ids(payload: Any, out: set[str]) -> None:
    """Collect chunk ids from a search/fetch result."""
    if isinstance(payload, dict):
        if isinstance(payload.get("id"), str):
            out.add(payload["id"])
        for cid in payload.get("chunk_ids") or []:
            out.add(str(cid))
        for v in payload.values():
            if isinstance(v, list | dict):
                _ids(v, out)
    elif isinstance(payload, list):
        for v in payload:
            _ids(v, out)


async def ask(session: ClientSession, http: httpx.AsyncClient, model: str, q: str) -> None:
    tools = _tools(await session.list_tools())
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": q},
    ]
    returned: set[str] = set()
    calls_log: list[str] = []
    t0 = time.monotonic()
    tool_s = 0.0
    answer = ""
    for round_ in range(MAX_ROUNDS + 1):
        body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 1500}
        if round_ < MAX_ROUNDS:
            body["tools"] = tools
        else:
            body["messages"] = messages + [{"role": "user", "content": FINAL_NUDGE}]
        r = await http.post("/chat/completions", json=body)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            answer = str(msg.get("content") or "")
            break
        messages.append(
            {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls}
        )
        for c in calls:
            fn = c["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            t1 = time.monotonic()
            res = await session.call_tool(fn["name"], args)
            tool_s += time.monotonic() - t1
            text = "".join(getattr(b, "text", "") for b in res.content)
            payload = res.structured_content
            if payload is None:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = None
            _ids(payload, returned)
            calls_log.append(f"{fn['name']}({json.dumps(args)})")
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": text[:8000]})
    total = time.monotonic() - t0
    cited = CITATION.findall(answer)
    print(f"\n## {q}\n")
    print(f"tool calls: {'; '.join(calls_log) or 'none'}")
    print(f"cited: {', '.join(f'{c}{"" if c in returned else " (NOT RETURNED)"}' for c in cited)}")
    print(f"time: {total:.1f} s total, {tool_s:.2f} s in MCP tools\n")
    print(answer.strip())


async def main(model: str, questions: list[str]) -> None:
    async with (
        streamable_http_client(MCP_URL) as (read, write, *_),
        ClientSession(read, write) as session,
        httpx.AsyncClient(base_url=STACK_URL, timeout=600) as http,
    ):
        init = await session.initialize()
        listed = await session.list_tools()
        print(f"MCP server: {init.server_info.name}; tools: {[t.name for t in listed.tools]}")
        t0 = time.monotonic()
        res = await session.call_tool("list_collections", {})
        print(f"list_collections ({time.monotonic() - t0:.2f} s):")
        print("".join(getattr(b, "text", "") for b in res.content)[:600])
        for q in questions:
            await ask(session, http, model, q)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
