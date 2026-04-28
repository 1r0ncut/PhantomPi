#!/usr/bin/env bash
# query-implant.sh — Universal PhantomPi implant API query script
#
# Usage:
#   bash query-implant.sh --alive  [ip1,ip2,...]   # TCP reachability only, no API call
#   bash query-implant.sh <endpoint> [ip1,ip2,...]  # full API query
#
# If no IPs are given, reads from $IMPLANT_IPS (comma-separated).
# Alive check: TCP connect to port 8443 — no dedicated /alive endpoint.
#
# Output: JSON object keyed by implant IP, e.g.:
#   --alive:   {"10.8.0.3": {"alive": true},  "10.8.0.4": {"alive": false}}
#   /status:   {"10.8.0.3": {"alive": true, "data": {...}}, "10.8.0.4": {"alive": false, "data": null}}

set -euo pipefail

MODE="${1:?Usage: query-implant.sh --alive|<endpoint> [ip1,ip2,...]}"
IPS_RAW="${2:-${IMPLANT_IPS:-}}"
PORT="${PORT:-8443}"
CONNECT_TIMEOUT=5
QUERY_TIMEOUT=10

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
