"""Thin client for the Llama Stack and llama.cpp APIs rag uses."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx


class StackClient:
    """Llama Stack: embeddings, vector stores, chunk insert and hybrid query."""

    def __init__(self, base_url: str, timeout: float = 300.0) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        r = self._http.post(path, json=body)
        r.raise_for_status()
        return r.json() if r.content else None

    def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        data = self._post("/embeddings", {"model": model, "input": list(texts)})["data"]
        return [list(map(float, d["embedding"])) for d in sorted(data, key=lambda d: d["index"])]

    def create_vector_store(self, name: str, model: str, dim: int) -> str:
        vs = self._post(
            "/vector_stores",
            {
                "name": name,
                "embedding_model": model,
                "embedding_dimension": dim,
                "provider_id": "pgvector",
            },
        )
        return str(vs["id"])

    def insert_chunks(self, vector_store_id: str, chunks: list[dict[str, Any]]) -> None:
        self._post("/vector-io/insert", {"vector_store_id": vector_store_id, "chunks": chunks})

    def delete_chunks(self, vector_store_id: str, chunk_ids: Sequence[str]) -> None:
        if not chunk_ids:
            return
        r = self._http.request(
            "DELETE",
            f"/vector_stores/{vector_store_id}/chunks",
            json={"chunks": [{"chunk_id": c, "document_id": c.rsplit("#", 1)[0]} for c in chunk_ids]},
        )
        if r.status_code == 404:
            # Older stacks only support deletion through the native vector-io API.
            r = self._http.post(
                "/vector-io/delete",
                json={
                    "vector_store_id": vector_store_id,
                    "chunks": [
                        {"chunk_id": c, "document_id": c.rsplit("#", 1)[0]} for c in chunk_ids
                    ],
                },
            )
        r.raise_for_status()

    def query(
        self, vector_store_id: str, query: str, max_chunks: int, mode: str = "hybrid"
    ) -> list[tuple[dict[str, Any], float]]:
        params: dict[str, Any] = {"mode": mode, "max_chunks": max_chunks}
        if mode == "hybrid":
            params["reranker_type"] = "rrf"
        res = self._post(
            "/vector-io/query",
            {"vector_store_id": vector_store_id, "query": query, "params": params},
        )
        return list(zip(res["chunks"], map(float, res["scores"]), strict=False))


class Reranker:
    """llama.cpp's /v1/rerank (cross-encoder)."""

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout)
        self._model = model

    def close(self) -> None:
        self._http.close()

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """Return one relevance score per document, in input order."""
        if not documents:
            return []
        r = self._http.post(
            "/rerank", json={"model": self._model, "query": query, "documents": list(documents)}
        )
        r.raise_for_status()
        scores = [0.0] * len(documents)
        for item in r.json()["results"]:
            scores[int(item["index"])] = float(item["relevance_score"])
        return scores
