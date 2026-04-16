#!/usr/bin/env bash
# -------------------------------------------------------------------
# Query PhantomPi implant status via the Flask API.
# Called by the OpenClaw implant-status skill.
#
# Usage:
#   bash check-status.sh alive  [IMPLANT_IP] [PORT]
#   bash check-status.sh status [IMPLANT_IP] [PORT]
# -------------------------------------------------------------------

set -euo pipefail

ACTION="${1:-status}"
IMPLANT_IP="${2:-10.8.0.3}"
PORT="${3:-8443}"
BASE="https://${IMPLANT_IP}:${PORT}"

case "$ACTION" in
    alive)
        HTTP_CODE=$(curl -sk --max-time 5 -o /dev/null -w "%{http_code}" \
            "${BASE}/alive" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            echo "{\"status\":\"alive\",\"ip\":\"${IMPLANT_IP}\",\"http_code\":${HTTP_CODE}}"
        else
            echo "{\"status\":\"dead\",\"ip\":\"${IMPLANT_IP}\",\"http_code\":${HTTP_CODE}}"
        fi
        ;;

    status)
        RESPONSE=$(curl -sk --max-time 10 "${BASE}/status" 2>/dev/null)
        if [ -n "$RESPONSE" ]; then
            echo "$RESPONSE"
        else
            echo "{\"error\":\"Implant at ${IMPLANT_IP} is unreachable\"}"
        fi
        ;;

    *)
        echo "{\"error\":\"Unknown action: ${ACTION}. Use 'alive' or 'status'.\"}"
        exit 1
        ;;
esac
