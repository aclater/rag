"""Generic ingestion: sections -> chunks -> embeddings -> a fresh vector store.

Re-ingest is all-or-nothing per collection: if every section's content hash
and the corpus version are unchanged, nothing happens. Otherwise a new vector
store is built side by side, the collection switches to it in one transaction,
and the old store is deleted. (Llama Stack 0.7.1 exposes no per-chunk delete,
and a side-by-side rebuild never leaves a half-updated index.)
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from rag import db
from rag.chunking import Chunk, SourceSection, chunk_section
from rag.config import Settings
from rag.stack import StackClient

log = logging.getLogger(__name__)
EMBED_BATCH = 32


@dataclass(frozen=True)
class CollectionSpec:
    name: str
    label: str  # short human label used in chunk headers, e.g. "MPEP"
    source: str
    corpus_version: str
    description: str


@dataclass(frozen=True)
class IngestReport:
    collection: str
    status: str  # "unchanged" | "built"
    sections: int
    chunks: int
    seconds: float
    vector_store_id: str


def content_hash(s: SourceSection, corpus_version: str) -> str:
    h = hashlib.sha256()
    for part in (corpus_version, s.section, s.title, s.parent or "", s.source_url, s.body):
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()


def _batches(items: Sequence[Chunk], n: int) -> Iterable[Sequence[Chunk]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


def ingest(
    spec: CollectionSpec,
    sections: Sequence[SourceSection],
    settings: Settings,
    *,
    force: bool = False,
) -> IngestReport:
    started = time.monotonic()
    if not sections:
        raise ValueError(f"no sections to ingest for {spec.name}")
    ids = [s.section for s in sections]
    dupes = {x for x in ids if ids.count(x) > 1}
    if dupes:
        raise ValueError(f"duplicate section ids in {spec.name}: {sorted(dupes)[:10]}")

    stack = StackClient(settings.stack_url)
    conn = db.connect(settings.db_dsn)
    try:
        db.migrate(conn)
        existing = db.get_collection(conn, spec.name)
        if existing:
            db.check_binding(existing, settings.embed_model, settings.embed_dim)
        hashes = {s.section: content_hash(s, spec.corpus_version) for s in sections}
        if (
            existing
            and not force
            and existing.corpus_version == spec.corpus_version
            and db.section_hashes(conn, spec.name) == hashes
        ):
            return IngestReport(
                spec.name,
                "unchanged",
                len(sections),
                0,
                time.monotonic() - started,
                existing.vector_store_id,
            )

        store = stack.create_vector_store(
            f"{spec.name}-{int(time.time())}", settings.embed_model, settings.embed_dim
        )
        log.info("building vector store %s for %s", store, spec.name)
        chunks_by_section: dict[str, list[Chunk]] = {
            s.section: chunk_section(spec.name, spec.label, s) for s in sections
        }
        by_id = {s.section: s for s in sections}
        all_chunks = [c for cs in chunks_by_section.values() for c in cs]
        done = 0
        for batch in _batches(all_chunks, EMBED_BATCH):
            vectors = stack.embed(settings.embed_model, [c.text for c in batch])
            payload: list[dict[str, Any]] = []
            for c, v in zip(batch, vectors, strict=True):
                s = by_id[c.section]
                meta = {
                    "collection": spec.name,
                    "section": s.section,
                    "title": s.title,
                    "parent": s.parent or "",
                    "source_url": s.source_url,
                    "corpus_version": spec.corpus_version,
                    "chunk_index": c.index,
                    "document_id": f"{spec.name}:{s.section}",
                }
                payload.append(
                    {
                        "content": c.text,
                        "chunk_id": c.chunk_id,
                        "metadata": meta,
                        "chunk_metadata": {
                            "chunk_id": c.chunk_id,
                            "document_id": meta["document_id"],
                            "source": s.source_url,
                        },
                        "embedding": v,
                        "embedding_model": settings.embed_model,
                        "embedding_dimension": settings.embed_dim,
                    }
                )
            stack.insert_chunks(store, payload)
            done += len(batch)
            if done % (EMBED_BATCH * 20) == 0:
                log.info("%s: %d/%d chunks", spec.name, done, len(all_chunks))

        # Switch atomically: sections and the collection's store change together.
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rag_section WHERE collection = %s", (spec.name,))
        if existing:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE rag_collection SET vector_store_id = %s, corpus_version = %s, "
                    "source = %s, description = %s, updated_at = now() WHERE name = %s",
                    (store, spec.corpus_version, spec.source, spec.description, spec.name),
                )
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO rag_collection (name, vector_store_id, embedding_model, "
                    "embedding_dim, source, corpus_version, description) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        spec.name,
                        store,
                        settings.embed_model,
                        settings.embed_dim,
                        spec.source,
                        spec.corpus_version,
                        spec.description,
                    ),
                )
        for s in sections:
            db.upsert_section(
                conn,
                db.Section(
                    collection=spec.name,
                    section=s.section,
                    title=s.title,
                    parent=s.parent,
                    source_url=s.source_url,
                    corpus_version=spec.corpus_version,
                    content_hash=hashes[s.section],
                    body=s.body,
                    chunk_ids=[c.chunk_id for c in chunks_by_section[s.section]],
                ),
            )
        conn.commit()
        if existing:
            stack.delete_vector_store(existing.vector_store_id)
        return IngestReport(
            spec.name, "built", len(sections), len(all_chunks), time.monotonic() - started, store
        )
    finally:
        conn.close()
        stack.close()
