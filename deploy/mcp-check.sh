#!/usr/bin/env bash
# End-to-end check through the MCP server: the chat model calls rag's tools over
# MCP (streamable HTTP) and answers with citations. Needs the pod running.
#
#   deploy/mcp-check.sh "question" ["question" ...]
#
# Uses the active profile's chat model; override with RAG_CHAT_MODEL.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROFILE=$(cat "${RAG_HOME:-$HOME/.local/share/rag}/runtime/profile" 2>/dev/null || echo laptop-light)
# shellcheck source=/dev/null
. "$HERE/profiles/$PROFILE.env"
[ $# -gt 0 ] || { echo "usage: $0 QUESTION..." >&2; exit 2; }
podman exec -i rag-mcp python - "${RAG_CHAT_MODEL:-chat/$CHAT_MODEL_ID}" "$@" <"$HERE/mcp-check.py"
