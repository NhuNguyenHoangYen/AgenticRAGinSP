#!/usr/bin/env bash
#
# Check that a running stack serves requests.
#
#   infra/scripts/smoke-test.sh            fast checks, no data written
#   infra/scripts/smoke-test.sh --ingest   also upload a small document and
#                                          wait until the worker indexes it
#                                          (creates a "smoke test" chat)
#
# Checks run inside the containers, so they need neither proxy credentials
# nor published ports. Exit status: 0 when every check passes.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

failures=0

check() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then
        log "PASS  $name"
    else
        log "FAIL  $name"
        failures=$((failures + 1))
    fi
}

http_ok() {  # http_ok <service> <url>: GET from inside a Python-based container
    compose exec -T "$1" python -c \
        "import urllib.request as u; u.urlopen('$2', timeout=10)"
}

worker_running() {
    [[ "$(compose ps --format '{{.State}}' worker)" == "running" ]]
}

proxy_requires_auth() {
    # busybox wget reports the status line on stderr; 401 proves auth is enforced.
    compose exec -T proxy sh -c \
        "wget -S -O /dev/null http://127.0.0.1:8080/ 2>&1 | grep -q ' 401 '"
}

# ---------------------------------------------------------------------------
# Optional end-to-end ingestion: chat -> upload -> worker -> ready.
# Runs in the API container against its own loopback address.
# ---------------------------------------------------------------------------
readonly INGEST_CHECK=$(cat <<'PY'
import json, time, urllib.request, uuid

API = "http://127.0.0.1:8000/api/v1"

def call(method, path, data=None, headers=None):
    request = urllib.request.Request(API + path, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())

chat = call("POST", "/chats", json.dumps({"title": "smoke test"}).encode(),
            {"Content-Type": "application/json"})
boundary = uuid.uuid4().hex
text = f"Smoke test document {uuid.uuid4().hex}.\n".encode()
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"smoke.txt\"\r\n"
        f"Content-Type: text/plain\r\n\r\n").encode() + text + f"\r\n--{boundary}--\r\n".encode()
upload = call("POST", f"/chats/{chat['id']}/documents", body,
              {"Content-Type": f"multipart/form-data; boundary={boundary}"})
assert upload["accepted"] == 1, upload

deadline = time.time() + 300
while time.time() < deadline:
    status = call("GET", f"/chats/{chat['id']}/documents")["items"][0]["status"]
    if status in ("ready", "failed"):
        break
    time.sleep(3)
assert status == "ready", f"document status: {status}"
PY
)

ingest_roundtrip() {
    compose exec -T api python -c "$INGEST_CHECK"
}

main() {
    local ingest=false
    case "${1:-}" in
        "") ;;
        --ingest) ingest=true ;;
        *) echo "Usage: $(basename "$0") [--ingest]" >&2; exit 64 ;;
    esac

    log "Smoke testing project '$PROJECT'"
    check "api /health/ready (MongoDB reachable)" http_ok api http://127.0.0.1:8000/health/ready
    check "ui /_stcore/health"                    http_ok ui http://127.0.0.1:8501/_stcore/health
    check "worker running"                        worker_running
    check "proxy /healthz"                        compose exec -T proxy wget -q -O /dev/null http://127.0.0.1:8080/healthz
    check "proxy enforces Basic Auth"             proxy_requires_auth
    if [[ "$ingest" == true ]]; then
        check "ingestion round trip (upload -> ready)" ingest_roundtrip
    fi

    if (( failures > 0 )); then
        die "$failures check(s) failed"
    fi
    log "All checks passed"
}

main "$@"
