"""Answer-level evaluation: a real chat turn per case, with the model calling the tools.

The chat model (through Llama Stack's OpenAI-compatible API) gets the same
search and fetch tools the MCP server exposes, runs up to MAX_ROUNDS of tool
calls, and answers. Scored per eval/README.md:
  citation accuracy   cited ids that (a) were returned by a tool call in the turn
                      and (b) match an expected source
  citation coverage   expected sources the answer cites
  content checks      must_mention present, must_not_mention absent
  abstention          false-abstention and missed-abstention rates
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from rag.evaluate import matches
from rag.search import Searcher

MAX_ROUNDS = 6
# Square brackets as instructed; gpt-oss sometimes uses its native 【】 instead,
# and models group several ids in one bracket: [mpep:608.01(n)#0, mpep:608.01(n)#1].
CITATION_ID = re.compile(r"[a-z0-9_-]+:[0-9A-Za-z.()]+#\d+")
CITATION_GROUP = re.compile(r"[\[【]([^\]】\n]{1,400})[\]】]")


def citations(answer: str) -> list[str]:
    """Cited ids in order of appearance."""
    return [
        cid
        for group in CITATION_GROUP.findall(answer)
        for cid in CITATION_ID.findall(group)
        if re.fullmatch(rf"\s*(?:{CITATION_ID.pattern}[\s,;]*)+", group)
    ]


ABSTAIN = re.compile(
    r"(does not|doesn't|do not|don't) (cover|address|contain|include|say|mention|have)|"
    r"no (relevant )?(information|guidance|section)|not (covered|addressed) (in|by)|"
    r"(could not|couldn't|cannot|can't) find|outside (the )?(scope|corpus)",
    re.I,
)
SYSTEM = (
    "You answer questions using only the user's indexed document collections. "
    "Always call the search tool first; call fetch for more context when needed. "
    "Cite every claim with the result id in square brackets, e.g. [mpep:2143#0], "
    "using only ids returned by the tools. If the collections don't cover the "
    "question, say that the collections don't cover it and cite nothing."
)
FINAL_NUDGE = (
    "Answer now from the tool results above, citing ids in square brackets, or say "
    "that the collections don't cover the question."
)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search indexed collections. Returns ranked chunks with citable ids.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch",
            "description": "Fetch the full source section for a result id or section id.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
]


def _call_tool(searcher: Searcher, name: str, args: dict[str, Any], returned: set[str]) -> str:
    try:
        if name == "search":
            results = searcher.search(str(args.get("query", "")), None, int(args.get("k", 8)))
            for r in results:
                returned.add(r.id)
            return json.dumps(
                [
                    {"id": r.id, "section": r.section, "title": r.title, "text": r.text[:1500]}
                    for r in results
                ]
            )
        if name == "fetch":
            sec = searcher.fetch(str(args.get("id", "")))
            for cid in sec.get("chunk_ids", []):
                returned.add(str(cid))
            return json.dumps(
                {k: sec[k] for k in ("section", "title", "chunk_ids")}
                | {"text": str(sec["text"])[:6000]}
            )
    except Exception as e:  # report tool errors to the model rather than abort the case
        return json.dumps({"error": str(e)})
    return json.dumps({"error": f"unknown tool {name}"})


def chat_turn(
    http: httpx.Client, model: str, searcher: Searcher, question: str
) -> tuple[str, set[str], int]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    returned: set[str] = set()
    for round_ in range(MAX_ROUNDS + 1):
        body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 1500}
        if round_ < MAX_ROUNDS:
            body["tools"] = TOOLS
        else:
            # Out of tool rounds: without this, some models return an empty message.
            body["messages"] = messages + [{"role": "user", "content": FINAL_NUDGE}]
        r = http.post("/chat/completions", json=body)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return str(msg.get("content") or ""), returned, round_
        messages.append(
            {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls}
        )
        for c in calls:
            fn = c["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "content": _call_tool(searcher, fn["name"], args, returned),
                }
            )
    return "", returned, MAX_ROUNDS


def score_answer(case: dict[str, Any], answer: str, returned: set[str]) -> dict[str, Any]:
    cited = citations(answer)
    cited_sections = [c.split(":", 1)[1].split("#", 1)[0] for c in cited]
    expected = [str(s) for s in case.get("expected_sources") or []]
    grounded = [c for c in cited if c in returned]
    correct = [
        c
        for c, s in zip(cited, cited_sections, strict=True)
        if c in returned and any(matches(s, e) for e in expected)
    ]
    abstained = bool(ABSTAIN.search(answer)) and not cited
    low = answer.lower()
    return {
        "cited": cited,
        "citation_grounded": (len(grounded) / len(cited)) if cited else None,
        "citation_accuracy": (len(correct) / len(cited)) if cited else None,
        "citation_coverage": (
            sum(1 for e in expected if any(matches(s, e) for s in cited_sections)) / len(expected)
            if expected
            else None
        ),
        "must_mention_ok": all(t.lower() in low for t in case.get("must_mention") or []),
        "must_not_mention_ok": not any(
            t.lower() in low for t in case.get("must_not_mention") or []
        ),
        "abstained": abstained,
        "expect_abstain": bool(case.get("expect_abstain")),
    }


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def run_answers(searcher: Searcher, golden: Path, model: str, label: str = "") -> dict[str, Any]:
    spec = yaml.safe_load(golden.read_text())
    http = httpx.Client(base_url=searcher.settings.stack_url, timeout=600)
    rows: list[dict[str, Any]] = []
    try:
        for case in spec["cases"]:
            t0 = time.monotonic()
            try:
                answer, returned, rounds = chat_turn(http, model, searcher, case["question"])
                error = None
            except httpx.HTTPError as e:
                answer, returned, rounds, error = "", set(), 0, str(e)
            row = {
                "id": case["id"],
                "type": case["type"],
                "seconds": round(time.monotonic() - t0, 1),
            }
            row |= score_answer(case, answer, returned) | {"tool_rounds": rounds, "error": error}
            row["answer"] = answer[:2000]
            row["returned"] = sorted(returned)
            rows.append(row)
    finally:
        http.close()
    non_abstain = [r for r in rows if not r["expect_abstain"]]
    abstain = [r for r in rows if r["expect_abstain"]]
    summary = {
        "cases": len(rows),
        "errors": sum(1 for r in rows if r["error"]),
        "citation_grounded": _mean(
            [r["citation_grounded"] for r in rows if r["citation_grounded"] is not None]
        ),
        "citation_accuracy": _mean(
            [r["citation_accuracy"] for r in rows if r["citation_accuracy"] is not None]
        ),
        "citation_coverage": _mean(
            [r["citation_coverage"] for r in non_abstain if r["citation_coverage"] is not None]
        ),
        "must_mention_rate": _mean([1.0 if r["must_mention_ok"] else 0.0 for r in rows]),
        "must_not_mention_rate": _mean([1.0 if r["must_not_mention_ok"] else 0.0 for r in rows]),
        "false_abstention_rate": _mean([1.0 if r["abstained"] else 0.0 for r in non_abstain]),
        "missed_abstention_rate": _mean([0.0 if r["abstained"] else 1.0 for r in abstain]),
        "mean_seconds_per_case": _mean([float(r["seconds"]) for r in rows]),
    }
    return {
        "label": label,
        "collection": spec["collection"],
        "golden_set": golden.name,
        "chat_model": model,
        "embedding_model": searcher.settings.embed_model,
        "summary": summary,
        "cases": rows,
    }
