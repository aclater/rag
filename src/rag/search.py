"""Hybrid retrieval with cross-encoder reranking, plus section fetch."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from rag import db
from rag.config import Settings
from rag.stack import Reranker, StackClient

DEFAULT_K = 10
CANDIDATES = 40  # per collection, from Llama Stack's hybrid (keyword + vector, RRF) query


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
        rerank: bool = True,
        candidates: int = CANDIDATES,
    ) -> list[Result]:
        query = query.strip()
        if not query:
            return []
        k = max(1, min(k, 50))
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
        results = list(pool.values())
        if rerank and results:
            scores = self.reranker.rerank(query, [r.text for r in results])
            results = [
                Result(**{**r.as_dict(), "score": s}) for r, s in zip(results, scores, strict=True)
            ]
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]

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
