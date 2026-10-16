#!/usr/bin/env bash
# Download the models a profile needs and verify each against its sha256.
#
#   models/fetch.sh [PROFILE]     default: laptop-light
#
# Files land in $RAG_MODELS (default ~/.local/share/rag/models). Downloads
# resume after interruption; a file whose checksum doesn't match is rejected.
set -euo pipefail
PROFILE=${1:-laptop-light}
DEST=${RAG_MODELS:-$HOME/.local/share/rag/models}
MANIFEST="$(cd "$(dirname "$0")" && pwd)/models.tsv"
mkdir -p "$DEST"
grep -v '^#' "$MANIFEST" | while IFS=$'\t' read -r file url sha role profiles _; do
    [ -n "$file" ] || continue
    case ",$profiles," in *",all,"*|*",$PROFILE,"*) ;; *) continue ;; esac
    out="$DEST/$file"
    if [ -f "$out" ] && echo "$sha  $out" | sha256sum -c --quiet 2>/dev/null; then
        echo "ok      $role  $file"
        continue
    fi
    echo "fetch   $role  $file"
    curl -fL --retry 5 --retry-all-errors -C - -o "$out.part" "$url"
    if echo "$sha  $out.part" | sha256sum -c --quiet; then
        mv "$out.part" "$out"
        echo "ok      $role  $file"
    else
        # Never resume onto a bad partial: move it aside so the next run starts clean.
        mv -f "$out.part" "$out.bad"
        echo "checksum mismatch: $file (moved to $out.bad; rerun to download afresh)" >&2
        exit 1
    fi
done
