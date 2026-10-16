#!/usr/bin/env bash
# Fetch the public USPTO MPEP (Ninth Edition, Revision 01.2024), verify it, and
# index it into the running rag pod.
#
#   deploy/ingest-mpep.sh [--force]
#
# Parsed chapters are cached, so re-runs only re-embed when something changed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RAG_HOME=${RAG_HOME:-$HOME/.local/share/rag}
CORPUS=$RAG_HOME/corpus/mpep
URL=https://www.uspto.gov/web/offices/pac/mpep/e9r-01-2024.zip
SHA256=a91cb1a2231b8e66ca9f87300f663f897c4ff7c2c6174dd31d0a2a8dc058efc5
# shellcheck source=/dev/null
. "$HERE/images.env"

mkdir -p "$CORPUS/pdf" "$RAG_HOME/cache/mpep"
if ! echo "$SHA256  $CORPUS/e9r-01-2024.zip" | sha256sum -c --quiet 2>/dev/null; then
    curl -fL --retry 5 -A 'Mozilla/5.0' -o "$CORPUS/e9r-01-2024.zip" "$URL"
    echo "$SHA256  $CORPUS/e9r-01-2024.zip" | sha256sum -c --quiet
fi
python3 -I -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \
    "$CORPUS/e9r-01-2024.zip" "$CORPUS/pdf"

TAG=$(git -C "$HERE/.." rev-parse --short HEAD 2>/dev/null || echo dev)
if [ -n "$(git -C "$HERE/.." status --porcelain 2>/dev/null)" ]; then TAG=dev; fi
if [ "$TAG" = dev ] || ! podman image exists "localhost/rag-ingest:$TAG"; then
    podman build -q --build-arg "BASE=$UBI_PYTHON_IMAGE" -f "$HERE/images/ingest/Containerfile" \
        -t "localhost/rag-ingest:$TAG" "$HERE/.." >/dev/null
fi

podman run --rm --name rag-ingest-mpep --pod rag --cpus=12 --memory=20g \
    --secret rag-db-password,type=env,target=POSTGRES_PASSWORD \
    -e RAG_INGEST_WORKERS="${RAG_INGEST_WORKERS:-3}" -e OMP_NUM_THREADS=3 \
    -v "$CORPUS/pdf:/data:ro,z" -v "$RAG_HOME/cache/mpep:/cache:Z,U" \
    "localhost/rag-ingest:$TAG" ingest mpep /data --cache /cache "$@"
