"""Retrieval evaluation over the golden sets in eval/ (see eval/README.md).

Metrics, per case and aggregated per collection and per case type:
  recall@5, recall@10, recall@20   share of expected sources in the top k
  MRR                              1/rank of the first matching result (0 if none in top 20)
  exact-match recall@5             recall@5 over `exact_match` cases only

A result matches an expected source if its section equals it or is a
subsection of it ("2143.01" satisfies "2143"; "2143" does not satisfy "2143.01").
Cases with no expected sources (abstain) are excluded.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from rag.search import Searcher

KS = (5, 10, 20)


def matches(section: str, expected: str) -> bool:
    return section == expected or (
        section.startswith(expected) and section[len(expected) : len(expected) + 1] in {".", "("}
    )


@dataclass(frozen=True)
class CaseResult:
    id: str
    type: str
    expected: list[str]
    ranked_sections: list[str]
    recall: dict[int, float]
    reciprocal_rank: float
    seconds: float


def score_case(expected: Sequence[str], ranked: Sequence[str]) -> tuple[dict[int, float], float]:
    recall = {}
    for k in KS:
        top = ranked[:k]
        hit = sum(1 for e in expected if any(matches(s, e) for s in top))
        recall[k] = hit / len(expected)
    rr = 0.0
    for i, s in enumerate(ranked[: max(KS)], start=1):
        if any(matches(s, e) for e in expected):
            rr = 1.0 / i
            break
    return recall, rr


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(results: Sequence[CaseResult]) -> dict[str, Any]:
    out: dict[str, Any] = {"cases": len(results)}
    for k in KS:
        out[f"recall@{k}"] = round(_mean([r.recall[k] for r in results]), 4)
    out["mrr"] = round(_mean([r.reciprocal_rank for r in results]), 4)
    exact = [r for r in results if r.type == "exact_match"]
    out["exact_match_recall@5"] = round(_mean([r.recall[5] for r in exact]), 4)
    out["exact_match_cases"] = len(exact)
    by_type: dict[str, Any] = {}
    for t in sorted({r.type for r in results}):
        rs = [r for r in results if r.type == t]
        by_type[t] = {
            "cases": len(rs),
            "recall@5": round(_mean([r.recall[5] for r in rs]), 4),
            "recall@10": round(_mean([r.recall[10] for r in rs]), 4),
            "mrr": round(_mean([r.reciprocal_rank for r in rs]), 4),
        }
    out["by_type"] = by_type
    out["mean_seconds_per_query"] = round(_mean([r.seconds for r in results]), 3)
    return out


def _git_revision() -> str:
    if os.environ.get("RAG_GIT_REVISION"):
        return os.environ["RAG_GIT_REVISION"]
    try:
        return subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run(
    searcher: Searcher,
    golden: Path,
    *,
    mode: str = "hybrid",
    rerank: bool = True,
    label: str = "",
) -> dict[str, Any]:
    spec = yaml.safe_load(golden.read_text())
    collection = spec["collection"]
    results: list[CaseResult] = []
    for case in spec["cases"]:
        expected = [str(s) for s in case.get("expected_sources") or []]
        if not expected:
            continue
        t0 = time.monotonic()
        ranked = searcher.search(case["question"], [collection], max(KS), mode=mode, rerank=rerank)
        seconds = time.monotonic() - t0
        sections = [r.section for r in ranked]
        recall, rr = score_case(expected, sections)
        results.append(
            CaseResult(case["id"], case["type"], expected, sections, recall, rr, seconds)
        )
    report = {
        "label": label,
        "collection": collection,
        "golden_set": golden.name,
        "golden_corpus_version": spec.get("corpus_version"),
        "mode": mode,
        "rerank": rerank,
        "embedding_model": searcher.settings.embed_model,
        "rerank_model": searcher.settings.rerank_model if rerank else None,
        "git_revision": _git_revision(),
        "profile": os.environ.get("RAG_PROFILE", ""),
        "summary": aggregate(results),
        "cases": [
            {
                "id": r.id,
                "type": r.type,
                "expected": r.expected,
                "top5": r.ranked_sections[:5],
                "recall@5": r.recall[5],
                "rr": round(r.reciprocal_rank, 4),
            }
            for r in results
        ],
    }
    return report


def write_report(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{report['collection']}-{report['mode']}-{'rerank' if report['rerank'] else 'norerank'}"
    if report.get("label"):
        name += f"-{report['label']}"
    path = out_dir / f"{name}-{time.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2))
    return path
