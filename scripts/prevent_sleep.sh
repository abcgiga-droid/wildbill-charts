#!/usr/bin/env bash
# prevent_sleep.sh — Prevent the Mac from sleeping
#
# Usage:
#   ./prevent_sleep.sh            # Prevent sleep indefinitely (until Ctrl+C)
#   ./prevent_sleep.sh 3600       # Prevent sleep for 3600 seconds (1 hour)
#   ./prevent_sleep.sh 2h         # Prevent sleep for 2 hours (suffix: s/m/h)
#   ./prevent_sleep.sh 90m        # Prevent sleep for 90 minutes
#
# Options:
#   -d    Prevent display from sleeping (default: on)
#   -i    Prevent system from idle sleeping (default: on)
#
# Press Ctrl+C to stop.

set -euo pipefail

# --- Parse optional duration argument ---
duration_arg="${1:-}"

# --- Convert human-readable duration to seconds ---
parse_duration() {
    local input="$1"
    local num suffix

    if [[ "$input" =~ ^([0-9]+)([smh])?$ ]]; then
        num="${BASH_REMATCH[1]}"
        suffix="${BASH_REMATCH[2]:-}"
        case "$suffix" in
            s) echo "$num" ;;
            m) echo "$(( num * 60 ))" ;;
            h) echo "$(( num * 3600 ))" ;;
            *) echo "$num" ;;  # no suffix → treat as seconds
        esac
    else
        echo "Error: Invalid duration '$input'. Use a number with optional suffix s/m/h." >&2
        exit 1
    fi
}

# --- Build caffeinate arguments ---
caffeinate_args=(-i -d)  # -i: prevent idle sleep, -d: prevent display sleep

if [[ -n "$duration_arg" ]]; then
    seconds=$(parse_duration "$duration_arg")
    caffeinate_args+=(-t "$seconds")
    echo "☕ Preventing sleep for ${seconds}s (press Ctrl+C to stop early)..."
else
    echo "☕ Preventing sleep indefinitely (press Ctrl+C to stop)..."
fi

# --- Run caffeinate ---
# shellcheck disable=SC2086
exec caffeinate "${caffeinate_args[@]}"
