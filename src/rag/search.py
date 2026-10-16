"""Hybrid retrieval with optional cross-encoder reranking, plus section fetch."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from rag import db
from rag.config import Settings
from rag.stack import Reranker, StackClient

DEFAULT_K = 10
CANDIDATES = 30  # per collection, from Llama Stack's hybrid (keyword + vector, RRF) query
RERANK_CHARS = 4000  # whole chunk: header plus up to chunking.MAX_CHARS of body
PINNED_CHUNKS = 2  # chunks of an explicitly named section placed first
# Section-like identifiers, e.g. 2143, 2143.01, 2164.01(a), 608.01(n).
IDENTIFIER = re.compile(r"(?<![\w.])(\d{2,4}(?:\.\d{1,2})?(?:\([a-z0-9]{1,3}\))*)(?![\w(])")


@dataclass(frozen=True)
class Result:
    id: str
    collection: str
    section: str
    title: str
    text: str
    score: float
    source_url: str
    corpus_version: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_text(c) for c in content)
    if isinstance(content, dict):
        return str(content.get("text", ""))
    return str(content)


class Searcher:
    """Holds the clients so the MCP server and the eval harness reuse connections."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stack = StackClient(settings.stack_url)
        self.reranker = Reranker(settings.rerank_url, settings.rerank_model)
        # Tunables, overridable for evaluation runs.
        self.candidates = int(os.environ.get("RAG_CANDIDATES", CANDIDATES))
        self.rerank_chars = int(os.environ.get("RAG_RERANK_CHARS", RERANK_CHARS))
        # "replace": order by the reranker's score; "rrf": fuse the hybrid rank
        # and the rerank rank with reciprocal rank fusion.
        self.rerank_fusion = os.environ.get("RAG_RERANK_FUSION", "replace")
        # Off by default: on the MPEP eval the llama.cpp port of the Granite
        # reranker lowers recall@5 and MRR (docs/ingest-and-search.md).
        self.rerank_default = os.environ.get("RAG_RERANK", "0") == "1"

    def close(self) -> None:
        self.stack.close()
        self.reranker.close()

    def _collections(self, names: Sequence[str] | None) -> list[db.Collection]:
        conn = db.connect(self.settings.db_dsn)
        try:
            wanted = list(names) if names else [str(c["name"]) for c in db.list_collections(conn)]
            found = [db.get_collection(conn, n) for n in wanted]
        finally:
            conn.close()
        missing = [n for n, c in zip(wanted, found, strict=True) if c is None]
        if missing:
            raise ValueError(f"unknown collection(s): {', '.join(missing)}")
        return [c for c in found if c is not None]

    def search(
        self,
        query: str,
        collections: Sequence[str] | None = None,
        k: int = DEFAULT_K,
        *,
        mode: str = "hybrid",
        rerank: bool | None = None,
        candidates: int | None = None,
    ) -> list[Result]:
        query = query.strip()
        if not query:
            return []
        k = max(1, min(k, 50))
        candidates = candidates or self.candidates
        if rerank is None:
            rerank = self.rerank_default
        pool: dict[str, Result] = {}
        for c in self._collections(collections):
            db.check_binding(c, self.settings.embed_model, self.settings.embed_dim)
            for chunk, score in self.stack.query(c.vector_store_id, query, candidates, mode=mode):
                meta = chunk.get("metadata") or {}
                cid = str(chunk.get("chunk_id") or meta.get("document_id"))
                if cid in pool:
                    continue
                pool[cid] = Result(
                    id=cid,
                    collection=c.name,
                    section=str(meta.get("section", "")),
                    title=str(meta.get("title", "")),
                    text=_text(chunk.get("content", "")),
                    score=score,
                    source_url=str(meta.get("source_url", "")),
                    corpus_version=str(meta.get("corpus_version", c.corpus_version)),
                )
        results = sorted(pool.values(), key=lambda r: r.score, reverse=True)
        if rerank and results:
            scores = self.reranker.rerank(query, [r.text[: self.rerank_chars] for r in results])
            if self.rerank_fusion == "rrf":
                by_rerank = sorted(range(len(results)), key=lambda i: scores[i], reverse=True)
                rerank_rank = {i: pos for pos, i in enumerate(by_rerank)}
                fused = [
                    1.0 / (60 + i + 1) + 1.0 / (60 + rerank_rank[i] + 1)
                    for i in range(len(results))
                ]
                results = [
                    Result(**{**r.as_dict(), "score": f})
                    for r, f in zip(results, fused, strict=True)
                ]
            else:
                results = [
                    Result(**{**r.as_dict(), "score": s})
                    for r, s in zip(results, scores, strict=True)
                ]
            results.sort(key=lambda r: r.score, reverse=True)
        pinned = self._pinned(query, collections, pool)
        if pinned:
            ids = {r.id for r in pinned}
            results = pinned + [r for r in results if r.id not in ids]
        return results[:k]

    def _pinned(
        self, query: str, collections: Sequence[str] | None, pool: dict[str, Result]
    ) -> list[Result]:
        """Chunks of sections the query names explicitly (e.g. "MPEP 2164.01(a)").

        Cross-encoders score bare identifiers poorly, so an exact, existing section
        id in the query is honoured deterministically: that section's first chunks
        go first, in the order the ids appear.
        """
        ids = list(dict.fromkeys(IDENTIFIER.findall(query)))
        if not ids:
            return []
        out: list[Result] = []
        conn = db.connect(self.settings.db_dsn)
        try:
            for c in self._collections(collections):
                for sid in db.existing_sections(conn, c.name, ids):
                    sec = db.get_section(conn, c.name, sid)
                    if sec is None:
                        continue
                    for cid in list(sec.chunk_ids)[:PINNED_CHUNKS]:
                        known = pool.get(cid)
                        out.append(
                            Result(
                                id=cid,
                                collection=c.name,
                                section=sec.section,
                                title=sec.title,
                                text=known.text if known else sec.body[: self.rerank_chars],
                                score=1000.0,  # above any rerank or fusion score
                                source_url=sec.source_url,
                                corpus_version=sec.corpus_version,
                            )
                        )
        finally:
            conn.close()
        return out

    def fetch(self, chunk_or_section: str, collection: str | None = None) -> dict[str, Any]:
        """Return a whole source section, given a chunk id ("mpep:2143.01#2") or a section id."""
        ref = chunk_or_section.strip()
        if ":" in ref:
            collection, rest = ref.split(":", 1)
            section = rest.split("#", 1)[0]
        else:
            section = ref
        conn = db.connect(self.settings.db_dsn)
        try:
            names = (
                [collection] if collection else [str(c["name"]) for c in db.list_collections(conn)]
            )
            for name in names:
                s = db.get_section(conn, name, section)
                if s is not None:
                    return {
                        "collection": s.collection,
                        "section": s.section,
                        "title": s.title,
                        "parent": s.parent,
                        "source_url": s.source_url,
                        "corpus_version": s.corpus_version,
                        "text": s.body,
                        "chunk_ids": list(s.chunk_ids),
                    }
        finally:
            conn.close()
        raise LookupError(f"no section {section!r} found")

    def list_collections(self) -> list[dict[str, object]]:
        conn = db.connect(self.settings.db_dsn)
        try:
            return db.list_collections(conn)
        finally:
            conn.close()
