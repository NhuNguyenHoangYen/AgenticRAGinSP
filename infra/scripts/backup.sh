#!/usr/bin/env bash
#
# Back up everything the stack cannot rebuild: MongoDB, Qdrant collections
# and uploaded originals. Runs against the live stack.
#
#   infra/scripts/backup.sh
#
#   BACKUP_ROOT  destination (default: ~/backups/<project>)
#   BACKUP_KEEP  number of backups to keep (default: 7)
#
# Layout of one backup:
#   <BACKUP_ROOT>/<UTC timestamp>/
#     mongo.archive.gz         mongodump --archive --gzip of the whole instance
#     qdrant/<name>.snapshot   one Qdrant snapshot per collection
#     uploads.tar.gz           the uploads volume
#     MANIFEST                 what was backed up, from which build
#     SHA256SUMS               verified by restore.sh before it touches data
#
# Consistency: each part is consistent on its own, but the three are taken one
# after another. A document uploaded during the run may exist in one part and
# not another; the worker's reconcile step repairs such states after restore.
# For a strictly consistent copy, stop api and worker first.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

readonly BACKUP_ROOT="${BACKUP_ROOT:-${HOME}/backups/${PROJECT}}"
readonly BACKUP_KEEP="${BACKUP_KEEP:-7}"

# ---------------------------------------------------------------------------
# Qdrant helpers, executed in the API container (it can reach qdrant:6333).
# ---------------------------------------------------------------------------
readonly QDRANT_LIST=$(cat <<'PY'
import json, os, urllib.request as u
collections = json.load(u.urlopen(os.environ["QDRANT_URL"] + "/collections", timeout=30))
print("\n".join(c["name"] for c in collections["result"]["collections"]))
PY
)

# Create a snapshot, stream it to stdout, then delete it from Qdrant storage.
readonly QDRANT_SNAPSHOT=$(cat <<'PY'
import json, os, shutil, sys, urllib.request as u
base = f"{os.environ['QDRANT_URL']}/collections/{sys.argv[1]}/snapshots"
created = u.urlopen(u.Request(base + "?wait=true", method="POST"), timeout=1800)
name = json.load(created)["result"]["name"]
try:
    with u.urlopen(f"{base}/{name}", timeout=1800) as response:
        shutil.copyfileobj(response, sys.stdout.buffer)
finally:
    u.urlopen(u.Request(f"{base}/{name}", method="DELETE"), timeout=60)
PY
)

prune_old_backups() {
    local old
    # Timestamped names sort chronologically; keep the newest BACKUP_KEEP.
    while read -r old; do
        [[ -n "$old" ]] || continue
        log "Removing old backup $(basename "$old")"
        rm -rf -- "$old"
    done < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*Z' | sort | head -n "-${BACKUP_KEEP}")
}

main() {
    [[ $# -eq 0 ]] || { echo "Usage: $(basename "$0")" >&2; exit 64; }
    [[ "$BACKUP_KEEP" =~ ^[1-9][0-9]*$ ]] || die "BACKUP_KEEP must be a positive integer"
    require_stack_files
    [[ "$(compose ps --format '{{.State}}' api)" == "running" ]] || die "the api service must be running"

    local stamp target partial
    stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
    target="${BACKUP_ROOT}/${stamp}"
    # Work in a .partial directory and rename at the end, so an interrupted
    # run never looks like a complete backup.
    partial="${target}.partial"
    mkdir -p "${partial}/qdrant"
    chmod 700 "$BACKUP_ROOT" "$partial"
    trap 'rm -rf -- "$partial"' EXIT

    log "Backing up project '$PROJECT' to $target"

    log "MongoDB"
    compose exec -T mongodb mongodump --archive --gzip --quiet > "${partial}/mongo.archive.gz"

    log "Qdrant"
    local collections collection
    collections="$(compose exec -T api python -c "$QDRANT_LIST")"
    while read -r collection; do
        [[ -n "$collection" ]] || continue
        [[ "$collection" =~ ^[A-Za-z0-9_-]+$ ]] || die "unexpected collection name: $collection"
        log "  collection $collection"
        compose exec -T api python -c "$QDRANT_SNAPSHOT" "$collection" > "${partial}/qdrant/${collection}.snapshot"
    done <<< "$collections"

    log "Uploads"
    compose exec -T api tar -czf - -C /app/var/uploads . > "${partial}/uploads.tar.gz"

    {
        echo "created_utc=${stamp}"
        echo "project=${PROJECT}"
        echo "commit=$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
        echo "image_tag=$(env_value IMAGE_TAG local)"
        echo "mongodb_database=$(env_value MONGODB_DATABASE agentic_rag)"
        echo "qdrant_collections=$(tr '\n' ' ' <<< "$collections" | sed 's/ *$//')"
    } > "${partial}/MANIFEST"

    (cd "$partial" && find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS)

    mv -- "$partial" "$target"
    trap - EXIT
    log "Backup complete: $target ($(du -sh "$target" | cut -f1))"

    prune_old_backups
}

main "$@"
