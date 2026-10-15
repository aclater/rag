# CLAUDE.md: rag

Instructions for coding agents working in this repository. Read
[README.md](README.md) and [docs/architecture.md](docs/architecture.md) first.

## What this project is

A local, private knowledge base that answers questions with citations. It
ingests document collections (the first is the USPTO MPEP), stores text and
vectors in PostgreSQL, and exposes retrieval as MCP tools that a tool-calling
model drives. It runs as one rootless Podman pod on a single machine. It
succeeds the archived `rag-suite` repositories (April 2026); see #1 for the
items carried over.

## Standing constraints

- **Red Hat technologies wherever they fit.** UBI 10 base images; rootless
  Podman quadlets in one pod; SELinux enforcing; RamaLama for model serving
  (llama.cpp, Vulkan on AMD); Llama Stack (pinned, Red Hat's Open Data Hub/RHOAI
  build) as the RAG and agent API with the pgvector vector store; RHEL-family
  PostgreSQL with pgvector; Docling for parsing. Use something else only when
  there's no Red Hat option, and say why in the PR.
- **No Chinese-origin models**, including Western-branded models built on
  Chinese base weights. Before adding any model, check its Hugging Face card
  (`base_model`) **and** its `config.json` architecture, and record the result in
  `models/models.tsv`. Current picks: gpt-oss-20b (laptop), gpt-oss-120b (home),
  IBM Granite 4 (light chat), IBM granite-embedding-english-r2 and
  granite-embedding-reranker-english-r2.
- **The embedding model is bound to the index.** A collection records its
  embedding model and dimension; writes with any other model are rejected.
  Changing it means building a new index side by side.
- **Closed by default.** Only the chat UI publishes a port (localhost unless
  configured). No service binds 0.0.0.0 on the host. No secrets in the repo:
  use podman secrets or local env files that are gitignored.
- **This repository is public.** No personal details: no home network names,
  hostnames, IP plans, trusted Wi-Fi names, travel plans or private collection
  contents. Private collection definitions live outside the repo.
- **Host resources.** Test VMs only through `~/.local/bin/vm-run`. Every
  container gets CPU and memory limits.

## Checks before every PR

```bash
ruff check . && ruff format --check .
mypy src
pytest -q
```

Semgrep and CodeQL run in CI and must stay clean.

## Workflow

- Every task starts with an issue. Claim it with a comment
  ("🤖 Claude Code picking up this issue."), log decisions and results there.
- **Docs always ship with the change**: features, fixes and process changes
  alike, in the same PR (README, docs/, this file, usage text).
- PRs say `Closes #N`. Wait for CI; merge only when every check passes.
- **AI review.** The `ai-review` workflow posts a review from a second model on
  each PR and after each push. Read the review of the latest push and answer
  every finding (fix it, or reply with why not) before merging. If it hasn't
  arrived 15 minutes after the last push, say so in the PR and merge on green.
- Commits explain why, one logical change each, and end with the
  `Co-Authored-By:` trailer for the model in use.
- Verify every version (images, packages, actions, models) from its primary
  source before using it; prefer releases at least two weeks old; pin images by
  digest and actions by commit SHA.
