# Architecture

## Goals

- Answer questions over document collections **with citations** that point at
  the exact sections used.
- Run entirely on one machine (a laptop or a small AI workstation), private by
  construction.
- Few moving parts: off-the-shelf components wherever possible, one small
  application for what's specific to this project.
- Model flexibility through configuration, not code.

## Components

| Component | Choice | Role |
| --- | --- | --- |
| Model serving | **RamaLama** (llama.cpp, Vulkan on AMD) | OpenAI-compatible endpoints for chat, embeddings (`--embedding`) and reranking (`--reranking`) |
| RAG and agent API | **Llama Stack** (Red Hat's Open Data Hub/RHOAI build, pinned) | Model provider abstraction (profiles), vector stores, OpenAI-compatible chat/responses, MCP tool runtime |
| Database | **PostgreSQL + pgvector** (RHEL-family image) | Documents, chunks, metadata and vectors in one transactional store |
| Parsing | **Docling** | PDF/DOCX/HTML to structured text with headings and tables preserved |
| Retrieval tools | This repo (`src/rag`) | MCP server: `search`, `fetch`, `list_collections`; ingestion connectors; citation checks |
| Chat UI | Open WebUI | The only published service; talks to Llama Stack and the MCP tools |
| Runtime | Rootless Podman quadlets in one pod, UBI 10 images, SELinux enforcing | |

## Request flow

1. The user asks a question in Open WebUI (or any MCP-capable client).
2. The chat model decides to call `search(query, collections, filters)`, as many
   times as it needs (multi-hop questions become several calls).
3. `search` runs **hybrid retrieval** (keyword + vector, fused with reciprocal
   rank fusion), optionally reranks the candidates with the reranker (off by
   default; see [ingest-and-search.md](ingest-and-search.md)), and returns chunk
   ids, text, source and section metadata.
4. `fetch(id)` returns surrounding context or a whole section when a snippet
   isn't enough.
5. The model answers, citing chunk ids. Citations are checked against the ids
   actually returned during the conversation.

## Data model

- `collection`: name, description, **embedding model id and dimension** (writes
  with any other model are rejected), source and version (e.g. the MPEP
  edition), last ingest time.
- `document`: collection, source URI, content hash (for incremental ingest).
- `chunk`: document, position, text, contextual header, structural metadata
  (e.g. MPEP `section` = `"2143.01"`), keyword index, embedding.

One schema, owned by this repository's migrations. No service creates its own
tables.

## Ingestion

Connectors are plugins in `src/rag/connectors`. Each one fetches, then parses
with Docling, chunks by document structure (headings and sections, not fixed
windows), adds a short contextual header per chunk, embeds with the
collection's model, and writes. Re-ingest touches only changed documents.

The first connector is the **USPTO Manual of Patent Examining Procedure**
(public, Ninth Edition, Revision 01.2024), which is heavy on exact-match
queries (section numbers, statute and rule citations) and well suited to
testing hybrid retrieval.

## Models and profiles

Models are chosen per **profile**; each role (chat, embed, rerank) points at an
OpenAI-compatible endpoint.

| Profile | Chat | Embed | Rerank | Hardware |
| --- | --- | --- | --- | --- |
| `laptop-light` | IBM Granite 4.0-H-Micro | granite-embedding-english-r2 | granite-embedding-reranker-english-r2 | Any recent iGPU |
| `laptop` | gpt-oss-20b | same | same | 32 GB+ GPU-addressable memory (e.g. Radeon 890M) |
| `workstation` | gpt-oss-120b | same | same | 96 GB+ unified memory (e.g. Strix Halo) |

Measured speeds for these and other candidate chat models on the `laptop`
hardware are in [models.md](models.md).

Rules:

- **No Chinese-origin models**, including models built on Chinese base weights.
  Each model's Hugging Face `base_model` and `config.json` architecture are
  checked and recorded in `models/models.tsv` with the GGUF source and sha256.
- The embedding model must match the collection's index in every profile.
- Chat and reranker models are free to change per profile.

### Serving engine

llama.cpp (through RamaLama) is the engine today: Vulkan is the most mature
path on AMD integrated GPUs, and a single-user knowledge base doesn't benefit
much from batching. **vLLM** (Red Hat AI Inference Server) becomes interesting
with concurrent users or a discrete GPU, and **llm-d** only for multi-node
serving on OpenShift. Llama Stack treats the model server as a provider and
RamaLama can run either runtime, so switching is configuration. A measured
llama.cpp vs vLLM comparison is tracked in #1.

## Security

- One pod, internal network; only Open WebUI publishes a port, bound to
  localhost unless explicitly configured otherwise, with authentication on.
- Secrets via podman secrets; nothing secret in the repository.
- Only the model servers get `/dev/dri`. Nothing gets `/dev/kfd`,
  `--privileged` or `--ipc=host`. SELinux labelling stays on.
- Images pinned by digest; GitHub Actions pinned by commit SHA; CodeQL and
  Semgrep in CI; Dependabot with a 14-day cooldown.

## Evaluation

`eval/` holds versioned golden questions per collection with the sections a
correct answer must cite. Retrieval metrics (recall@k, MRR) run in CI against
the search tool; answer quality runs on demand. Model, chunking and retrieval
changes report their numbers.

## Open questions

- Hybrid search in Llama Stack's pgvector provider (#13): if it lacks a keyword
  mode, the search tool adds PostgreSQL full-text search and fuses the results.
- Remote access to a workstation-hosted instance from a laptop: undecided; the
  default is local only.
