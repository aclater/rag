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
   rank fusion. 30 candidates per collection (`RAG_CANDIDATES`).
2. **Pinning.** Section ids written in the query (`§ 2143.01`, `2106`) pin
   that section's first chunks to the top, so exact-reference questions never
   depend on ranking.
3. **Optional rerank** with the Granite cross-encoder (llama.cpp
   `/v1/rerank`). Off by default; see the numbers below. Turn it on with
   `RAG_RERANK=1` (or `--rerank` on the CLI). `RAG_RERANK_CHARS` (default
   4000, the whole chunk) and `RAG_RERANK_FUSION` (`replace` orders by the
   reranker's score; `rrf` fuses hybrid and rerank ranks) tune it.
4. Return the top `k` with citable ids (`mpep:2143.01#0`), section, title,
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
deploy/eval.sh                          # the default path: hybrid, no rerank
deploy/eval.sh --rerank --label rerank
deploy/eval.sh --mode vector --label vector-only
RAG_EVAL_DEV=1 RAG_RERANK_FUSION=rrf deploy/eval.sh --rerank --label rrf
```

`RAG_EVAL_DEV=1` runs the working tree's `src/rag` instead of the image's, for
trying search changes without a rebuild. The search tunables above pass through
from the environment and are recorded in the report.

### Results: MPEP, laptop-light, 34 scored cases

| Setup | recall@5 | recall@10 | recall@20 | MRR | exact@5 | s/query |
|---|---|---|---|---|---|---|
| **hybrid, no rerank (default)** | **0.912** | 0.912 | 0.971 | **0.790** | 1.000 | 0.08 |
| hybrid, 60 candidates, no rerank | 0.912 | 0.912 | 0.971 | 0.790 | 1.000 | 0.08 |
| hybrid + llama.cpp rerank, 1500 chars | 0.750 | 0.882 | 0.941 | 0.565 | 0.889 | 2.5 |
| hybrid + llama.cpp rerank, whole chunk | 0.750 | 0.853 | 0.941 | 0.547 | 0.889 | 2.5 |
| hybrid + llama.cpp rerank, whole chunk, RRF | 0.853 | 0.926 | 0.985 | 0.752 | 1.000 | 2.5 |
| hybrid + reference reranker (transformers, CPU) | 0.809 | 0.926 | 1.000 | 0.823 | 1.000 | 20.9 |
| vector + llama.cpp rerank | 0.721 | 0.882 | 0.941 | 0.573 | 0.889 | 2.5 |

Truncation wasn't the problem: giving the reranker the whole chunk changed
nothing. The **llama.cpp port of granite-embedding-reranker-english-r2 scores
differently from the reference model**: on a four-document probe the reference
`ModernBertForSequenceClassification` gives logits 3.04 / 2.12 / 0.88 / 0.45
where llama-server gives 1.10 / 1.08 / 0.66 / 0.43, so relevant and irrelevant
passages barely separate. The reference model does improve MRR (0.823) and
recall@20 (1.000) but costs recall@5 and runs at 21 s/query on CPU, which is not
usable interactively. Hybrid retrieval without rerank is the default until the
GGUF reranker matches the reference (or a GPU-served reference reranker is
available); the reranker container stays in the pod for opt-in use.

Retrieval metrics don't depend on the chat model.

### Answer-level results: which chat model

`deploy/eval.sh --answers chat/<model>` runs each case as a real chat turn:
the model gets the same `search`/`fetch` tools, up to six tool rounds, and
answers with citations; scoring is defined in [eval/README.md](../eval/README.md).
MPEP, 38 cases, hybrid retrieval without rerank, one run each on a Radeon 890M
laptop with nothing else running:

| Chat model (profile) | grounded | citation accuracy | coverage | must-mention | false / missed abstention | s/case |
|---|---|---|---|---|---|---|
| **gpt-oss-20b** (`laptop`) | 1.000 | **0.875** | 0.779 | 0.737 | 0.03 / 0.33 | 70 |
| Gemma 4 26B-A4B (`laptop-gemma`) | 1.000 | 0.747 | **0.794** | **0.868** | 0.03 / **0.00** | 80 |
| Granite 4.0-H-Micro (`laptop-light`) | 0.938 | 0.125 | 0.029 | 0.658 | 0.20 / 1.00 | 48 |

- **gpt-oss-20b stays the `laptop` default**: the most precise citations, and it
  searches more (2.5 tool rounds per case against Gemma's 1.05). Gemma 4
  26B-A4B is a close alternative with better coverage and content recall.
- **Granite 4.0-H-Micro is not usable for cited answers**: it rarely cites ids,
  answers abstention questions from its own knowledge, and invents ids. Keep
  `laptop-light` for pipeline tests.
- Only three cases test abstention, so one case moves the rate by 0.33; a
  second gpt-oss run scored 0.00 missed abstention. Treat differences of a few
  points as noise until the eval set grows.

The models cite in their own styles: gpt-oss sometimes uses its native `【id】`
brackets, Gemma groups ids (`[id1, id2]`); the scorer accepts both, and every
citation is checked against the ids the tools actually returned in that turn.
