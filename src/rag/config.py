"""Runtime configuration from the environment (defaults match the pod)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    stack_url: str
    rerank_url: str
    embed_model: str
    embed_dim: int
    rerank_model: str
    db_dsn: str

    @classmethod
    def from_env(cls) -> Settings:
        password = os.environ.get("POSTGRES_PASSWORD", "")
        default_dsn = f"host=127.0.0.1 port=5432 dbname=rag user=rag password={password}"
        return cls(
            stack_url=os.environ.get("RAG_STACK_URL", "http://127.0.0.1:8321/v1").rstrip("/"),
            rerank_url=os.environ.get("RAG_RERANK_URL", "http://127.0.0.1:8082/v1").rstrip("/"),
            embed_model=os.environ.get("RAG_EMBED_MODEL", "embed/granite-embedding-english-r2"),
            embed_dim=int(os.environ.get("RAG_EMBED_DIM", "768")),
            rerank_model=os.environ.get("RAG_RERANK_MODEL", "granite-embedding-reranker-english-r2"),
            db_dsn=os.environ.get("RAG_DB_DSN", default_dsn),
        )
