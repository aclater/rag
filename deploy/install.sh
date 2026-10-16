#!/usr/bin/env bash
# Render the quadlets for a profile, create secrets, and start the rag pod.
#
#   deploy/install.sh [PROFILE]      default: laptop-light
#
# Quadlets go to ~/.config/containers/systemd/; runtime config (Llama Stack
# config, database init) is copied to $RAG_HOME/runtime so the repo itself is
# never relabelled by SELinux. Re-running updates the deployment in place.
set -euo pipefail
PROFILE=${1:-laptop-light}
HERE="$(cd "$(dirname "$0")" && pwd)"
RAG_HOME=${RAG_HOME:-$HOME/.local/share/rag}
MODELS=${RAG_MODELS:-$RAG_HOME/models}
RUNTIME=$RAG_HOME/runtime
QUADLETS=${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd

[ -f "$HERE/profiles/$PROFILE.env" ] || { echo "unknown profile: $PROFILE" >&2; exit 2; }
# shellcheck source=/dev/null
. "$HERE/images.env"
# shellcheck source=/dev/null
. "$HERE/profiles/$PROFILE.env"

for f in "$CHAT_MODEL_FILE" "$EMBED_MODEL_FILE" "$RERANK_MODEL_FILE"; do
    [ -f "$MODELS/$f" ] || { echo "missing model $MODELS/$f; run models/fetch.sh $PROFILE" >&2; exit 1; }
done

mkdir -p "$RUNTIME/stack" "$RUNTIME/db-init" "$QUADLETS"
install -m 0644 "$HERE/stack/config.yaml" "$RUNTIME/stack/config.yaml"
install -m 0644 "$HERE/db-init/10-pgvector.sh" "$RUNTIME/db-init/10-pgvector.sh"

# Pull images up front: a first pull inside a unit's start can outlast
# systemd's start timeout.
for img in "$RAMALAMA_IMAGE" "$LLAMA_STACK_IMAGE" "$POSTGRES_IMAGE" "$OPEN_WEBUI_IMAGE"; do
    podman image exists "$img" || podman pull -q "$img" >/dev/null
done

# This project's own MCP image, tagged by source revision.
APP_TAG=$(git -C "$HERE/.." rev-parse --short HEAD 2>/dev/null || echo dev)
if [ -n "$(git -C "$HERE/.." status --porcelain 2>/dev/null)" ]; then
    APP_TAG=dev  # uncommitted changes: always rebuild
    podman image rm -f localhost/rag-mcp:dev >/dev/null 2>&1 || true
fi
if ! podman image exists "localhost/rag-mcp:$APP_TAG"; then
    podman build -q --build-arg "BASE=$UBI_PYTHON_IMAGE" -f "$HERE/images/mcp/Containerfile" \
        -t "localhost/rag-mcp:$APP_TAG" "$HERE/.." >/dev/null
fi

# Secrets: generated once, stored only in podman's secret store.
for s in rag-db-password rag-db-admin-password; do
    podman secret exists "$s" || head -c 32 /dev/urandom | base64 | tr -d '/+=' | podman secret create "$s" - >/dev/null
done
# Open WebUI uses its secret as a Fernet key: URL-safe base64 of 32 bytes.
podman secret exists rag-webui-secret || head -c 32 /dev/urandom | base64 | tr '+/' '-_' | podman secret create rag-webui-secret - >/dev/null

render() {
    sed -e "s|@RAMALAMA_IMAGE@|$RAMALAMA_IMAGE|g" \
        -e "s|@LLAMA_STACK_IMAGE@|$LLAMA_STACK_IMAGE|g" \
        -e "s|@POSTGRES_IMAGE@|$POSTGRES_IMAGE|g" \
        -e "s|@OPEN_WEBUI_IMAGE@|$OPEN_WEBUI_IMAGE|g" \
        -e "s|@MODELS@|$MODELS|g" \
        -e "s|@RUNTIME@|$RUNTIME|g" \
        -e "s|@UI_PORT@|$UI_PORT|g" \
        -e "s|@CHAT_MODEL_FILE@|$CHAT_MODEL_FILE|g" \
        -e "s|@CHAT_MODEL_ID@|$CHAT_MODEL_ID|g" \
        -e "s|@CHAT_CTX@|$CHAT_CTX|g" \
        -e "s|@EMBED_MODEL_FILE@|$EMBED_MODEL_FILE|g" \
        -e "s|@EMBED_MODEL_ID@|$EMBED_MODEL_ID|g" \
        -e "s|@EMBED_DIM@|$EMBED_DIM|g" \
        -e "s|@RERANK_MODEL_FILE@|$RERANK_MODEL_FILE|g" \
        -e "s|@RERANK_MODEL_ID@|$RERANK_MODEL_ID|g" \
        -e "s|@APP_TAG@|$APP_TAG|g" "$1"
}
for t in "$HERE"/quadlet/*.in; do
    out="$QUADLETS/$(basename "${t%.in}")"
    render "$t" >"$out"
    if grep -q '@[A-Z_]*@' "$out"; then echo "unrendered placeholder in $out" >&2; exit 1; fi
done
echo "$PROFILE" >"$RUNTIME/profile"

systemctl --user daemon-reload
systemctl --user reset-failed 'rag-*' 2>/dev/null || true
systemctl --user restart rag-pod.service
echo "rag ($PROFILE) starting; UI on http://127.0.0.1:$UI_PORT once healthy."
echo "status: systemctl --user status 'rag-*'    logs: journalctl --user -u rag-stack -f"
