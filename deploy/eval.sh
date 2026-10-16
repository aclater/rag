#!/usr/bin/env bash
# Run the retrieval evaluation (eval/*.yaml) against the running rag pod.
#
#   deploy/eval.sh [rag eval options]       e.g. --label granite --rerank
#
# Search tunables pass through from the environment: RAG_RERANK, RAG_CANDIDATES,
# RAG_RERANK_CHARS, RAG_RERANK_FUSION (replace|rrf), RAG_RERANK_URL.
#
# Reports are written to eval/reports/ (gitignored).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
TAG=$(podman image ls --format '{{.Tag}}' localhost/rag-mcp | head -1)
[ -n "$TAG" ] || { echo "no rag-mcp image; run deploy/install.sh first" >&2; exit 1; }
mkdir -p "$REPO/eval/reports"
# RAG_EVAL_DEV=1 runs the working tree's src/rag instead of the image's copy,
# for trying search changes without rebuilding.
DEV=()
[ "${RAG_EVAL_DEV:-0}" = 1 ] && DEV=(-v "$REPO/src/rag:/opt/app-root/lib64/python3.12/site-packages/rag:ro,z")
PROFILE=$(cat "${RAG_HOME:-$HOME/.local/share/rag}/runtime/profile" 2>/dev/null || echo laptop-light)
# shellcheck source=/dev/null
. "$HERE/profiles/$PROFILE.env"
podman run --rm --pod rag --cpus=2 --memory=1g \
    --secret rag-db-password,type=env,target=POSTGRES_PASSWORD \
    -e RAG_EMBED_MODEL="embed/$EMBED_MODEL_ID" -e RAG_EMBED_DIM="$EMBED_DIM" \
    -e RAG_RERANK_MODEL="$RERANK_MODEL_ID" -e RAG_PROFILE="$PROFILE" \
    --env "RAG_RERANK*" --env "RAG_CANDIDATES*" --env "RAG_RERANK_CHARS*" --env "RAG_RERANK_FUSION*" --env "RAG_RERANK_URL*" \
    -e RAG_GIT_REVISION="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)" \
    "${DEV[@]}" -v "$REPO/eval:/eval:ro,z" -v "$REPO/eval/reports:/reports:Z,U" -w /eval \
    --entrypoint rag "localhost/rag-mcp:$TAG" eval /eval/mpep.yaml --out /reports "$@"
