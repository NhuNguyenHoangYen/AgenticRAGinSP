#!/usr/bin/env bash
#
# Restore a backup made by backup.sh. Replaces the current MongoDB data, the
# Qdrant collections contained in the backup and the uploaded originals.
#
#   infra/scripts/restore.sh <backup-dir> --yes
#
# Steps: verify checksums -> stop api, worker, ui, proxy -> restore MongoDB,
# Qdrant and uploads -> start the stack -> smoke test. --yes is required
# because the current data is overwritten.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Upload one snapshot (read from stdin) and let it replace the collection.
# Runs in a one-off container of the api service, which can reach qdrant:6333.
readonly QDRANT_RESTORE=$(cat <<'PY'
import os, sys, uuid, urllib.request as u
collection = sys.argv[1]
snapshot = sys.stdin.buffer.read()
boundary = uuid.uuid4().hex
body = (
    f"--{boundary}\r\nContent-Disposition: form-data; name=\"snapshot\"; "
    f"filename=\"{collection}.snapshot\"\r\nContent-Type: application/octet-stream\r\n\r\n"
).encode() + snapshot + f"\r\n--{boundary}--\r\n".encode()
url = (f"{os.environ['QDRANT_URL']}/collections/{collection}/snapshots/upload"
       "?priority=snapshot&wait=true")
request = u.Request(url, data=body, method="POST",
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
u.urlopen(request, timeout=1800).read()
PY
)

usage() {
    echo "Usage: $(basename "$0") <backup-dir> --yes" >&2
    exit 64
}

wait_for_data_stores() {
    local deadline=$((SECONDS + 120)) states
    while (( SECONDS < deadline )); do
        states="$(compose ps --format '{{.Service}}={{.Health}}' mongodb qdrant | sort | tr '\n' ' ')"
        [[ "$states" == "mongodb=healthy qdrant=healthy " ]] && return 0
        sleep 3
    done
    die "mongodb and qdrant did not become healthy"
}

main() {
    [[ $# -eq 2 && "$2" == "--yes" ]] || usage
    local backup
    backup="$(cd "$1" 2>/dev/null && pwd)" || die "backup directory not found: $1"
    [[ -f "${backup}/SHA256SUMS" && -f "${backup}/MANIFEST" ]] || die "not a backup made by backup.sh: $backup"
    require_stack_files

    log "Verifying checksums"
    (cd "$backup" && sha256sum --quiet -c SHA256SUMS) || die "checksum mismatch; backup is damaged"
    log "Restoring $(grep '^created_utc=' "${backup}/MANIFEST" | cut -d= -f2) into project '$PROJECT'"

    log "Stopping application services"
    compose stop proxy ui api worker
    compose up -d mongodb qdrant
    wait_for_data_stores

    log "MongoDB (dropping existing collections)"
    compose exec -T mongodb mongorestore --drop --archive --gzip --quiet < "${backup}/mongo.archive.gz"

    log "Qdrant"
    local snapshot collection
    for snapshot in "${backup}"/qdrant/*.snapshot; do
        [[ -e "$snapshot" ]] || continue
        collection="$(basename "$snapshot" .snapshot)"
        log "  collection $collection"
        compose run --rm --no-deps -T --entrypoint python api -c "$QDRANT_RESTORE" "$collection" < "$snapshot"
    done

    log "Uploads (replacing the volume contents)"
    compose run --rm --no-deps -T --entrypoint sh api -c \
        'find /app/var/uploads -mindepth 1 -delete && tar -xzf - -C /app/var/uploads' \
        < "${backup}/uploads.tar.gz"

    log "Starting the stack"
    compose up -d --no-build
    wait_for_stack 600 || die "stack did not become healthy after restore"
    "$(dirname "${BASH_SOURCE[0]}")/smoke-test.sh"
    log "Restore complete"
}

main "$@"
