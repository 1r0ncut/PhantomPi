#!/usr/bin/env bash
# -------------------------------------------------------------------
# Query status of a single PhantomPi implant via the Flask API.
# Called by the OpenClaw implant-status skill.
#
# Usage:
#   bash check-status.sh alive  [IMPLANT_IP] [PORT]
#   bash check-status.sh status [IMPLANT_IP] [PORT]
# -------------------------------------------------------------------

set -euo pipefail

ACTION="${1:-status}"
IMPLANT_IP="${2:-${IMPLANT_IPS:-10.8.0.3}}"
PORT="${3:-8443}"
BASE="https://${IMPLANT_IP}:${PORT}"

case "$ACTION" in
    alive)
        HTTP_CODE=$(curl -sk --max-time 5 -o /dev/null -w "%{http_code}" \
            "${BASE}/alive" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            echo "{\"implant\":\"${IMPLANT_IP}\",\"status\":\"alive\",\"http_code\":${HTTP_CODE}}"
        else
            echo "{\"implant\":\"${IMPLANT_IP}\",\"status\":\"dead\",\"http_code\":${HTTP_CODE}}"
        fi
        ;;

    status)
        RESPONSE=$(curl -sk --max-time 10 "${BASE}/status" 2>/dev/null || echo "")
        if [ -n "$RESPONSE" ]; then
            echo "$RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    d['implant'] = '${IMPLANT_IP}'
    print(json.dumps(d))
except:
    print(json.dumps({'implant':'${IMPLANT_IP}','error':'bad response'}))
"
        else
            echo "{\"implant\":\"${IMPLANT_IP}\",\"error\":\"unreachable\"}"
        fi
        ;;

    *)
        echo "{\"error\":\"Unknown action: ${ACTION}. Use 'alive' or 'status'.\"}"
        exit 1
        ;;
esac
