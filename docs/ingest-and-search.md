# Ingestion, retrieval and evaluation

## Ingestion

Connectors turn a source into **sections** (one per natural unit of the
document), and the generic pipeline (`src/rag/ingest.py`) does the rest:

1. **Chunk by structure.** A section yields one or more chunks
   (`src/rag/chunking.py`); chunks never cross a section boundary, long
   sections split on paragraphs with a one-paragraph overlap. Each chunk starts
   with a contextual header such as `MPEP § 2143.01 Suggestion or Motivation To
   Modify the References (part of 2143)`, which is embedded and keyword-indexed
   with the text, so identifiers stay searchable inside every chunk.
2. **Embed** through Llama Stack with the collection's embedding model.
3. **Insert** into a pgvector vector store through Llama Stack, with per-chunk
   metadata (`collection`, `section`, `title`, `parent`, `source_url`,
   `corpus_version`).
4. **Record** the collection (its embedding model, dimension and corpus
   version) and every section's full text and content hash in rag's own tables.

**The embedding model is bound to the collection.** Ingesting or searching with
a different model or dimension fails with an explicit error.

**Re-ingest is side by side.** If the corpus version and every section's
content hash are unchanged, nothing happens. Otherwise a new vector store is
built, the collection switches to it in one transaction, and the old store is
deleted. (Llama Stack 0.7.1 has no per-chunk delete; a side-by-side rebuild
also never leaves a half-updated index.)

### MPEP connector

`src/rag/connectors/mpep.py`, run with `deploy/ingest-mpep.sh`:

- **Source:** the official USPTO archive `e9r-01-2024.zip` (Ninth Edition,
  Revision 01.2024), verified by sha256. The 29 chapter PDFs are indexed; front
  matter and appendices (statutes, rules, index) aren't yet.
- **Parsing:** Docling (layout model on CPU, no OCR: the PDFs have a text
  layer), chapters in parallel worker processes; parsed chapters are cached by
  file hash so re-runs skip parsing.
- **Sections:** every MPEP section heading ends with a revision tag, e.g.
  `2143.01 Suggestion or Motivation To Modify the References [R-01.2024]`; those
  headings are the section boundaries. Statute and rule headers (35 U.S.C.,
  37 CFR) and Roman-numeral subheadings stay inside their section;
  `[Reserved]` ranges, page headers and footers are dropped.
- **Corpus version** `Ninth Edition, Revision 01.2024` is recorded on the
  collection and on every chunk.

## Retrieval

`search(query, collections, k)` (`src/rag/search.py`):

1. **Hybrid candidates** from Llama Stack's pgvector store: keyword
   (PostgreSQL full-text search) and vector similarity, fused with reciprocal
   rank fusion. 40 candidates per collection.
2. **Rerank** the candidates with the Granite cross-encoder (llama.cpp
   `/v1/rerank`).
3. Return the top `k` with citable ids (`mpep:2143.01#0`), section, title,
   text, score, source URL and corpus version.

`fetch(id)` returns the whole section for a chunk id or section id, from rag's
own tables. `list_collections()` reports what's indexed.

These are exposed as MCP tools by `rag-mcp` (streamable HTTP,
`http://127.0.0.1:8090/mcp` inside the pod) and configured in Open WebUI. The
same functions back the CLI:

```bash
podman exec rag-mcp rag search "KSR obviousness rationales"
podman exec rag-mcp rag fetch mpep:2143
podman exec rag-mcp rag collections
```

## Evaluation

`deploy/eval.sh` runs `rag eval eval/mpep.yaml` inside the pod and writes a
JSON report to `eval/reports/` (gitignored), recording the profile, models,
mode and git revision. Metrics are defined in [eval/README.md](../eval/README.md):
recall@5/10/20, MRR and exact-match recall@5, per case type.

```bash
deploy/eval.sh                          # hybrid + rerank (the default path)
deploy/eval.sh --no-rerank --label norerank
deploy/eval.sh --mode vector --label vector-only
```

Retrieval metrics don't depend on the chat model. Answer-level metrics
(citation accuracy, abstention) need a chat turn per case and are the next
step; see eval/README.md.
