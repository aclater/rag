#!/usr/bin/env bash
# Stop the rag pod and remove its quadlets. Data volumes and secrets are kept
# unless --purge is given.
set -euo pipefail
QUADLETS=${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd
systemctl --user stop rag-pod.service 2>/dev/null || true
rm -f "$QUADLETS"/rag.pod "$QUADLETS"/rag-*.container
systemctl --user daemon-reload
if [ "${1:-}" = "--purge" ]; then
    podman volume rm -f rag-db-data rag-webui-data 2>/dev/null || true
    podman secret rm rag-db-password rag-db-admin-password rag-webui-secret 2>/dev/null || true
    echo "removed quadlets, volumes and secrets"
else
    echo "removed quadlets (volumes and secrets kept; --purge removes them)"
fi
