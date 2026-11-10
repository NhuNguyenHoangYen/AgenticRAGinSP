#!/usr/bin/env bash
#
# Create or update a Basic Auth user for the reverse proxy.
#
#   infra/scripts/create-htpasswd.sh <username>
#
# The password is read from the terminal (not echoed, not stored in shell
# history) and hashed with APR1-MD5, the scheme nginx verifies natively on
# every platform; bcrypt depends on the libc crypt() of the nginx image.
# Restart or reload the proxy after changing users.

set -euo pipefail

readonly HTPASSWD_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../proxy" && pwd)/htpasswd"

usage() {
    echo "Usage: $(basename "$0") <username>" >&2
    exit 64
}

main() {
    [[ $# -eq 1 ]] || usage
    local username="$1"

    if [[ ! "$username" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
        echo "Username may contain letters, digits, '.', '_' and '-' (max 64)." >&2
        exit 65
    fi
    command -v openssl >/dev/null || { echo "openssl is required." >&2; exit 69; }

    local password confirm
    read -r -s -p "Password for ${username}: " password; echo
    read -r -s -p "Repeat password: " confirm; echo
    [[ -n "$password" ]] || { echo "Password must not be empty." >&2; exit 65; }
    [[ "$password" == "$confirm" ]] || { echo "Passwords do not match." >&2; exit 65; }

    local entry
    entry="${username}:$(printf '%s' "$password" | openssl passwd -apr1 -stdin)"

    # Replace an existing entry for this user, keep the others. Written to a
    # temporary file first so a failed run never truncates the live file.
    touch "$HTPASSWD_FILE"
    local tmp
    tmp="$(mktemp "${HTPASSWD_FILE}.XXXXXX")"
    grep -v "^${username}:" "$HTPASSWD_FILE" > "$tmp" || true
    echo "$entry" >> "$tmp"
    # World-readable because nginx reads it as uid 101 through a bind mount.
    # The file only holds salted hashes, and home directories are 0750 on
    # current Ubuntu, so other host users cannot reach it.
    chmod 644 "$tmp"
    mv "$tmp" "$HTPASSWD_FILE"

    echo "Saved ${username} to ${HTPASSWD_FILE}"
}

main "$@"
