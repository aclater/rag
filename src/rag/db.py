"""rag's own tables: collections (embedding-model binding) and source sections."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources

import psycopg


@dataclass(frozen=True)
class Collection:
    name: str
    vector_store_id: str
    embedding_model: str
    embedding_dim: int
    source: str
    corpus_version: str
    description: str


@dataclass(frozen=True)
class Section:
    collection: str
    section: str
    title: str
    parent: str | None
    source_url: str
    corpus_version: str
    content_hash: str
    body: str
    chunk_ids: Sequence[str]


class EmbeddingModelMismatch(RuntimeError):
    """A collection is bound to a different embedding model than the one in use."""


def connect(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(dsn, autocommit=False)


def migrate(conn: psycopg.Connection[tuple[object, ...]]) -> list[str]:
    """Apply the bundled SQL migrations in order; return the names applied."""
    applied: list[str] = []
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS rag_schema_migration "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        cur.execute("SELECT name FROM rag_schema_migration")
        done = {str(row[0]) for row in cur.fetchall()}
        files = sorted(
            (f for f in resources.files("rag.migrations").iterdir() if f.name.endswith(".sql")),
            key=lambda f: f.name,
        )
        for f in files:
            if f.name in done:
                continue
            cur.execute(f.read_text())
            cur.execute("INSERT INTO rag_schema_migration (name) VALUES (%s)", (f.name,))
            applied.append(f.name)
    conn.commit()
    return applied


def get_collection(conn: psycopg.Connection[tuple[object, ...]], name: str) -> Collection | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, vector_store_id, embedding_model, embedding_dim, source, "
            "corpus_version, description FROM rag_collection WHERE name = %s",
            (name,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return Collection(
        name=str(row[0]),
        vector_store_id=str(row[1]),
        embedding_model=str(row[2]),
        embedding_dim=int(str(row[3])),
        source=str(row[4]),
        corpus_version=str(row[5]),
        description=str(row[6]),
    )


def list_collections(conn: psycopg.Connection[tuple[object, ...]]) -> list[dict[str, object]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.name, c.description, c.source, c.corpus_version, c.embedding_model, "
            "count(s.section), c.updated_at FROM rag_collection c "
            "LEFT JOIN rag_section s ON s.collection = c.name GROUP BY c.name ORDER BY c.name"
        )
        rows = cur.fetchall()
    return [
        {
            "name": r[0],
            "description": r[1],
            "source": r[2],
            "corpus_version": r[3],
            "embedding_model": r[4],
            "sections": r[5],
            "updated_at": str(r[6]),
        }
        for r in rows
    ]


def create_collection(conn: psycopg.Connection[tuple[object, ...]], c: Collection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rag_collection (name, vector_store_id, embedding_model, embedding_dim, "
            "source, corpus_version, description) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                c.name,
                c.vector_store_id,
                c.embedding_model,
                c.embedding_dim,
                c.source,
                c.corpus_version,
                c.description,
            ),
        )
    conn.commit()


def check_binding(c: Collection, embedding_model: str, embedding_dim: int) -> None:
    """Refuse to mix embedding models in one index."""
    if c.embedding_model != embedding_model or c.embedding_dim != embedding_dim:
        raise EmbeddingModelMismatch(
            f"collection {c.name!r} is bound to {c.embedding_model} ({c.embedding_dim}-d); "
            f"refusing to use {embedding_model} ({embedding_dim}-d). Build a new collection "
            "for a different embedding model."
        )


def section_hashes(conn: psycopg.Connection[tuple[object, ...]], collection: str) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT section, content_hash FROM rag_section WHERE collection = %s", (collection,)
        )
        return {str(r[0]): str(r[1]) for r in cur.fetchall()}


def section_chunk_ids(
    conn: psycopg.Connection[tuple[object, ...]], collection: str, section: str
) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_ids FROM rag_section WHERE collection = %s AND section = %s",
            (collection, section),
        )
        row = cur.fetchone()
    return [str(x) for x in row[0]] if row and isinstance(row[0], list) else []


def upsert_section(conn: psycopg.Connection[tuple[object, ...]], s: Section) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rag_section (collection, section, title, parent, source_url, "
            "corpus_version, content_hash, body, chunk_ids) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (collection, section) DO UPDATE SET title = EXCLUDED.title, "
            "parent = EXCLUDED.parent, source_url = EXCLUDED.source_url, "
            "corpus_version = EXCLUDED.corpus_version, content_hash = EXCLUDED.content_hash, "
            "body = EXCLUDED.body, chunk_ids = EXCLUDED.chunk_ids, updated_at = now()",
            (
                s.collection,
                s.section,
                s.title,
                s.parent,
                s.source_url,
                s.corpus_version,
                s.content_hash,
                s.body,
                list(s.chunk_ids),
            ),
        )


def get_section(
    conn: psycopg.Connection[tuple[object, ...]], collection: str, section: str
) -> Section | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT collection, section, title, parent, source_url, corpus_version, "
            "content_hash, body, chunk_ids FROM rag_section WHERE collection = %s AND section = %s",
            (collection, section),
        )
        r = cur.fetchone()
    if r is None:
        return None
    return Section(
        collection=str(r[0]),
        section=str(r[1]),
        title=str(r[2]),
        parent=None if r[3] is None else str(r[3]),
        source_url=str(r[4]),
        corpus_version=str(r[5]),
        content_hash=str(r[6]),
        body=str(r[7]),
        chunk_ids=[str(x) for x in r[8]] if isinstance(r[8], list) else [],
    )


def touch_collection(conn: psycopg.Connection[tuple[object, ...]], name: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE rag_collection SET updated_at = now() WHERE name = %s", (name,))
