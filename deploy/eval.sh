#!/usr/bin/env bash
# Run the retrieval evaluation (eval/*.yaml) against the running rag pod.
#
#   deploy/eval.sh [rag eval options]       e.g. --label granite --no-rerank
#
# Reports are written to eval/reports/ (gitignored).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
TAG=$(podman image ls --format '{{.Tag}}' localhost/rag-mcp | head -1)
[ -n "$TAG" ] || { echo "no rag-mcp image; run deploy/install.sh first" >&2; exit 1; }
mkdir -p "$REPO/eval/reports"
PROFILE=$(cat "${RAG_HOME:-$HOME/.local/share/rag}/runtime/profile" 2>/dev/null || echo laptop-light)
# shellcheck source=/dev/null
. "$HERE/profiles/$PROFILE.env"
podman run --rm --pod rag --cpus=2 --memory=1g \
    --secret rag-db-password,type=env,target=POSTGRES_PASSWORD \
    -e RAG_EMBED_MODEL="embed/$EMBED_MODEL_ID" -e RAG_EMBED_DIM="$EMBED_DIM" \
    -e RAG_RERANK_MODEL="$RERANK_MODEL_ID" -e RAG_PROFILE="$PROFILE" \
    -e RAG_GIT_REVISION="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)" \
    -v "$REPO/eval:/eval:ro,z" -v "$REPO/eval/reports:/reports:Z,U" -w /eval \
    --entrypoint rag "localhost/rag-mcp:$TAG" eval /eval/mpep.yaml --out /reports "$@"
