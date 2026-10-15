# rag

A local, private knowledge base that answers questions **with citations**.
Documents are parsed, chunked by structure and indexed in PostgreSQL
(pgvector). Retrieval is exposed as a small set of MCP tools, so any
tool-calling model or agent (the bundled Open WebUI, Claude Code, others) can
search, read and cite the sources. Everything runs on one machine in a single
rootless Podman pod; nothing leaves it.

> Status: **walking skeleton**. The architecture is settled
> ([docs/architecture.md](docs/architecture.md)); components land through the
> issues linked there. This project succeeds the archived `rag-suite`
> repositories (#1 lists what carried over).

## Design in one picture

```
            ┌────────────┐
  browser ─►│ Open WebUI │  only published port (localhost by default)
            └─────┬──────┘
 ┌ ─ ─ ─ ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─  rootless Podman pod, internal network ─ ─ ─ ┐
                  ▼
 │   ┌──────────────────────┐      ┌──────────────────────────────┐        │
     │ Llama Stack          │◄────►│ MCP tools: search, fetch,    │
 │   │ (OpenAI-compatible   │      │ list_collections             │        │
     │  API, vector stores) │      └──────────────┬───────────────┘
 │   └───┬────────┬─────────┘                     │                        │
         │        │                               │
 │   RamaLama model servers (llama.cpp, Vulkan)   │                        │
     ┌───▼──┐ ┌───▼───┐ ┌────────┐      ┌─────────▼──────────┐
 │   │ chat │ │ embed │ │ rerank │      │ PostgreSQL+pgvector│               │
     └──────┘ └───────┘ └────────┘      └────────────────────┘
 └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
```

## Principles

- **Red Hat technologies first:** UBI 10 images, Podman quadlets, SELinux,
  RamaLama, Llama Stack, RHEL-family PostgreSQL, Docling.
- **Open models, no Chinese-origin weights**, verified per model (see
  [models/models.tsv](models/models.tsv)): gpt-oss for chat, IBM Granite for
  embeddings, reranking and light chat.
- **Model profiles, not hard-coded models.** Chat and reranker models swap per
  profile; the embedding model is bound to each collection's index.
- **Hybrid retrieval with citations** that are checked against what was
  actually retrieved.
- **Closed by default:** one exposed port, no secrets in the repo.
- **Measured, not guessed:** an evaluation set (see `eval/`) gates retrieval and
  model changes.

## Quick start (developer machine)

Requirements: Fedora or RHEL with Podman 5, a Vulkan-capable GPU (AMD
Radeon 780M/890M or Strix Halo were the development targets), ~25 GB free disk.

```bash
git clone https://github.com/aclater/rag && cd rag
models/fetch.sh laptop-light       # download the profile's models, verify sha256
deploy/install.sh laptop-light     # render quadlets, create secrets, start the pod
```

The UI is then on http://127.0.0.1:3000 (first sign-up becomes the admin).
Profiles, containers, security choices and troubleshooting:
[docs/deploy.md](docs/deploy.md). Ingestion and the retrieval tools land in
#9 and #10.

See [docs/architecture.md](docs/architecture.md) for profiles, ports and
operations.

## License

Apache-2.0. See [LICENSE](LICENSE).
