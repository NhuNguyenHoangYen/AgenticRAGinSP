#!/usr/bin/env bash
#
# Build and (re)start the stack from the checked-out code, then verify it.
#
#   infra/scripts/deploy.sh                  build, start, wait, smoke test
#   infra/scripts/deploy.sh --rollback <tag> start a previously deployed build
#   infra/scripts/deploy.sh --list           show builds available for rollback
#
# Every deploy also tags the application images with the Git commit, so an
# earlier build can be started again without rebuilding. Compose itself always
# runs IMAGE_TAG from the env file ("local" by default); a rollback re-points
# that tag at the chosen commit's images.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

readonly CURRENT_TAG="$(env_value IMAGE_TAG local)"

usage() {
    sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 64
}

commit_tag() {
    git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Image tag bookkeeping
# ---------------------------------------------------------------------------
tag_images() {  # tag_images <from> <to>
    local image
    for image in "${APP_IMAGES[@]}"; do
        docker image inspect "${image}:$1" >/dev/null 2>&1 || die "image ${image}:$1 not found"
        docker tag "${image}:$1" "${image}:$2"
    done
}

list_builds() {
    docker image ls "${APP_IMAGES[0]}" --format '{{.Tag}}\t{{.CreatedSince}}' \
        | grep -v -E "^(${CURRENT_TAG}|<none>)\b" || true
}

# ---------------------------------------------------------------------------
# Deploy steps
# ---------------------------------------------------------------------------
start_and_verify() {
    log "Starting services"
    compose up -d --no-build --remove-orphans

    log "Waiting for services to become healthy"
    wait_for_stack 600 || die "deployment did not become healthy; inspect: docker compose -p $PROJECT logs"

    "$(dirname "${BASH_SOURCE[0]}")/smoke-test.sh"
}

deploy_current() {
    local commit
    commit="$(commit_tag)"
    if [[ -n "$commit" && -n "$(git -C "$REPO_ROOT" status --porcelain -- src infra requirements-*.txt)" ]]; then
        log "WARNING: uncommitted changes in src/, infra/ or requirements; the commit tag will not match the build"
    fi

    log "Building images (${CURRENT_TAG}${commit:+, commit $commit})"
    compose build --pull

    if [[ -n "$commit" ]]; then
        tag_images "$CURRENT_TAG" "$commit"
        log "Tagged build as $commit for rollback"
    fi

    start_and_verify
    log "Deployed ${commit:-working tree} to project '$PROJECT'"
}

rollback() {
    local tag="$1"
    log "Rolling back to build $tag"
    tag_images "$tag" "$CURRENT_TAG"
    start_and_verify
    log "Rolled back project '$PROJECT' to $tag"
}

main() {
    case "${1:-}" in
        "")         require_stack_files; deploy_current ;;
        --rollback) [[ $# -eq 2 ]] || usage; require_stack_files; rollback "$2" ;;
        --list)     list_builds ;;
        *)          usage ;;
    esac
}

main "$@"
