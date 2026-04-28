#!/usr/bin/env bash
# query-implant.sh: Universal PhantomPi implant API query script
#
# Usage:
#   bash query-implant.sh --alive   [ip1,ip2,...]          # TCP reachability only
#   bash query-implant.sh <endpoint> [ip1,ip2,...]          # GET, multi-implant
#   bash query-implant.sh --post <endpoint> <json> [ip]     # POST, single implant
#
# If no IPs are given, reads from $IMPLANT_IPS (comma-separated).
# Alive check: TCP connect to port 8443, no dedicated /alive endpoint.
#
# GET output:  JSON object keyed by implant IP
#   {"10.8.0.3": {"alive": true, "data": {...}}, ...}
# POST output: raw JSON response from the implant (single target)

set -euo pipefail

MODE="${1:?Usage: query-implant.sh --alive|--post|<endpoint> [...]}"
PORT="${PORT:-8443}"
CONNECT_TIMEOUT=5
QUERY_TIMEOUT=10

# POST mode: single implant
if [ "$MODE" = "--post" ]; then
    ENDPOINT="${2:?--post requires: <endpoint> <json> [ip]}"
    JSON_BODY="${3:?--post requires: <endpoint> <json> [ip]}"
    IPS_RAW="${4:-${IMPLANT_IPS:-}}"

    # Use only the first IP for write operations
    IP="${IPS_RAW%%,*}"
    IP="${IP// /}"

    if [ -z "$IP" ]; then
        printf '{"error":"No implant IP. Pass as fourth argument or set IMPLANT_IPS."}\n'
        exit 1
    fi

    if ! nc -z -w "$CONNECT_TIMEOUT" "$IP" "$PORT" 2>/dev/null; then
        printf '{"error":"implant %s unreachable on port %s"}\n' "$IP" "$PORT"
        exit 1
    fi

    curl -sk --max-time "$QUERY_TIMEOUT" \
        -X POST \
        -H "Content-Type: application/json" \
        -d "$JSON_BODY" \
        "https://${IP}:${PORT}${ENDPOINT}"

    exit 0
fi

# GET / --alive mode: multi-implant
IPS_RAW="${2:-${IMPLANT_IPS:-}}"

if [ -z "$IPS_RAW" ]; then
    printf '{"error":"No implant IPs. Pass as second argument or set IMPLANT_IPS."}\n'
    exit 1
fi

IFS=',' read -ra IPS <<< "$IPS_RAW"

entries=""
sep=""

for IP in "${IPS[@]}"; do
    IP="${IP// /}"
    [ -z "$IP" ] && continue

    if nc -z -w "$CONNECT_TIMEOUT" "$IP" "$PORT" 2>/dev/null; then
        if [ "$MODE" = "--alive" ]; then
            entries+="${sep}\"${IP}\":{\"alive\":true}"
        else
            DATA=$(curl -sk --max-time "$QUERY_TIMEOUT" \
                "https://${IP}:${PORT}${MODE}" 2>/dev/null || true)
            if [ -n "$DATA" ] && echo "$DATA" | python3 -c \
                "import sys, json; json.load(sys.stdin)" 2>/dev/null; then
                entries+="${sep}\"${IP}\":{\"alive\":true,\"data\":${DATA}}"
            else
                entries+="${sep}\"${IP}\":{\"alive\":true,\"data\":null,\"error\":\"bad response\"}"
            fi
        fi
    else
        if [ "$MODE" = "--alive" ]; then
            entries+="${sep}\"${IP}\":{\"alive\":false}"
        else
            entries+="${sep}\"${IP}\":{\"alive\":false,\"data\":null}"
        fi
    fi

    sep=","
done

printf '{%s}\n' "$entries"
