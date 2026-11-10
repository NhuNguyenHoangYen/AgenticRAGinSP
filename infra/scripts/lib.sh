# Shared helpers for the operations scripts. Source it, do not execute it.
#
# Overridable through the environment:
#   STACK_PROJECT  Compose project name            (default: agentic-rag)
#   STACK_ENV_FILE env file for Compose/containers (default: infra/env/stack.env)

# ---------------------------------------------------------------------------
# Paths and stack identity
# ---------------------------------------------------------------------------
readonly INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT="$(cd "${INFRA_DIR}/.." && pwd)"
readonly COMPOSE_FILE="${INFRA_DIR}/compose/compose.yaml"
readonly ENV_FILE="${STACK_ENV_FILE:-${INFRA_DIR}/env/stack.env}"
readonly HTPASSWD_FILE="${INFRA_DIR}/proxy/htpasswd"
readonly PROJECT="${STACK_PROJECT:-agentic-rag}"

# Images built by the stack; the tag comes from IMAGE_TAG in the env file.
readonly APP_IMAGES=(agentic-rag-backend agentic-rag-streamlit)

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
log()  { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }

# ---------------------------------------------------------------------------
# Compose wrapper: every script talks to the same project, file and env file.
# ---------------------------------------------------------------------------
compose() {
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

# Read KEY from the env file, falling back to a default. Mirrors how Compose
# interpolates the same file, without sourcing it (values are not shell code).
env_value() {
    local key="$1" default="${2:-}" value
    value="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2-)"
    printf '%s' "${value:-$default}"
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------
require_stack_files() {
    command -v docker >/dev/null || die "docker is not installed"
    docker compose version >/dev/null 2>&1 || die "the docker compose plugin is not installed"
    [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE (copy infra/env/stack.env.example)"
    [[ -f "$HTPASSWD_FILE" ]] || die "missing $HTPASSWD_FILE (run infra/scripts/create-htpasswd.sh <user>)"

    local mode
    mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo unknown)"
    [[ "$mode" == "600" ]] || log "WARNING: $ENV_FILE has mode $mode; it holds secrets, use chmod 600"
}

# ---------------------------------------------------------------------------
# Wait until every service is running and, where a health check exists,
# healthy. The worker has no health check and only needs to be running.
# ---------------------------------------------------------------------------
wait_for_stack() {
    local timeout="${1:-600}" deadline=$((SECONDS + ${1:-600})) expected pending

    expected="$(compose config --services | wc -l)"
    while (( SECONDS < deadline )); do
        pending="$(compose ps --all --format '{{.Service}} {{.State}} {{.Health}}' \
            | awk '$2 != "running" || ($3 != "" && $3 != "healthy")')"
        if [[ -z "$pending" && "$(compose ps --format '{{.Service}}' | wc -l)" -eq "$expected" ]]; then
            return 0
        fi
        sleep 5
    done

    log "Stack not healthy after ${timeout}s:"
    compose ps --all --format 'table {{.Service}}\t{{.State}}\t{{.Health}}\t{{.Status}}' >&2
    return 1
}
