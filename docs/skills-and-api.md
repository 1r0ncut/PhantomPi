# Implant API and OpenClaw Skills

How to add new capabilities to PhantomPi: new AI skills, new implant API endpoints, or both.

---

## Architecture

```
Operator (Discord)
      │
      ▼
  OpenClaw (VPS)          ← AI agent, reads skills, routes requests
      │
      │  HTTPS (WireGuard)
      ▼
  Implant API (Flask)     ← REST API served by Gunicorn on port 8443
      │
      ▼
  Implant internals       ← scripts, PCAPs, systemd services, logs
```

When the operator asks something in Discord, OpenClaw selects the matching skill, runs its script(s), calls the implant API if needed, and formats the response.

---

## Key files

### VPS side

| Path | Purpose |
|------|---------|
| `/home/openclaw/.openclaw/openclaw.json` | OpenClaw runtime config (agents, hooks, channels) |
| `/home/openclaw/.openclaw/.env` | Secrets (Discord token, API keys) |
| `/home/openclaw/scripts/query-implant.sh` | Universal implant query script (used by all skills) |
| `/home/openclaw/skills/<name>/SKILL.md` | Skill definition: triggers, instructions, output format |
| `/home/openclaw/skills/<name>/scripts/` | Optional skill-specific scripts |

### Implant side

| Path | Purpose |
|------|---------|
| `/opt/implant/config.env` | Central config, sourced by all services |
| `/opt/implant/api/app/routes/` | One `.py` file per API endpoint |
| `/opt/implant/scripts/` | Operator scripts and background analyzers |
| `/opt/implant/logs/<service>/` | Per-service log directories |
| `/opt/implant/services/` | systemd service unit files |
| `/opt/implant/timers/` | systemd timer unit files |

---

## Adding a new skill

A skill lives entirely on the VPS. It tells OpenClaw when to activate, what scripts to run, and how to format the response.

### 1. Create the skill directory

```
/home/openclaw/skills/<skill-name>/
├── SKILL.md
└── scripts/
    └── <script>.sh
```

### 2. Write `SKILL.md`

```markdown
---
name: my-skill
description: >
  One or two sentences describing what this skill does and what phrases trigger it.
  Triggers on: keyword1, keyword2, keyword3.
metadata: {"openclaw":{"requires":{"bins":["curl","nc"]},"os":["linux"]}}
---

# My Skill

Brief explanation of what this skill is for.

## How to use it

Describe when and how the agent should invoke the script.

\`\`\`bash
# Check reachability first (optional)
bash /home/openclaw/scripts/query-implant.sh --alive [IMPLANT_IP]

# GET endpoint (queries all implants in IMPLANT_IPS)
bash /home/openclaw/scripts/query-implant.sh /my-endpoint [IMPLANT_IP]

# POST endpoint (targets a single implant)
bash /home/openclaw/scripts/query-implant.sh --post /my-endpoint '{"key":"value"}' [IMPLANT_IP]
\`\`\`

## Interpreting the output

Explain what the script returns and how to present it.
```

> **Note:** Discord formatting rules (bold, inline code, fenced blocks — no tables, no headings, no HTML) are defined globally in `AGENTS.md` and apply to every skill. Do not repeat them here.

### 3. Write the script (optional)

Most skills call the implant API directly from `SKILL.md` using the universal
query script — no per-skill script is needed. Only add a script under
`skills/<name>/scripts/` when you need complex pre/post-processing that cannot
be done inline.

If you do write a helper script, call `query-implant.sh` rather than curling
the implant directly:

```bash
#!/usr/bin/env bash
set -euo pipefail

IMPLANT_IP="${1:-${IMPLANT_IPS%%,*}}"   # default: first IP in the list

RESPONSE=$(bash /home/openclaw/scripts/query-implant.sh /my-endpoint "$IMPLANT_IP")

# ... process $RESPONSE ...
echo "$RESPONSE"
```

### 4. Register the skill in OpenClaw config

Add the skill name to the `skills` list in `/home/openclaw/.openclaw/openclaw.json`:

```json
"agents": {
    "defaults": {
        "model": "anthropic/claude-sonnet-4-6",
        "skills": ["implant-status", "cred-sniffer", "bridge-sync", "my-skill"]
    }
}
```

### 5. Reload OpenClaw

```bash
sudo systemctl restart openclaw-gateway.service
```

Then type `/new` in Discord to start a fresh session that reads the updated skill list.

---

## Extending the implant API

Before writing a new skill, check whether the implant API already exposes the data you need:

| Endpoint | Returns |
|----------|---------|
| `GET /status` | Interface state, uptime, services, ports (clean JSON, no emojis) |
| `GET /captured-creds` | All extracted credentials and hashes |
| `GET /pivot-status` | Pivot readiness, spoofed identity from log, current veth1 routes, subnet suggestions from PCAPs |
| `POST /pivot-setup` | Add routes through veth1 for specified subnets; gateway read from spoof-target log |
| `POST /pivot-reset` | Remove specific or all routes from veth1 |
| `GET /ligolo-sessions` | List active `ligolo-*` tmux sessions with proxy IP and running state |
| `POST /ligolo-start` | Start ligolo-agent in a named tmux session connecting to operator's proxy |
| `POST /ligolo-kill` | Kill a specific ligolo session or all of them |

If the data you need is not available, add a new route.

### Adding a new API route

Each route lives in its own file under `implant/api/app/routes/`. The app auto-loads all `.py` files in that directory at startup, so no registration is needed beyond creating the file.

**1. Create `implant/api/app/routes/my_endpoint.py`:**

```python
"""
My endpoint: short description of what it returns.
"""

import json
import os
from flask import jsonify

def register(app):

    @app.route("/my-endpoint", methods=["GET"])
    def my_endpoint():
        # Collect data from the implant
        data = {}
        return jsonify(data)
```

**2. Deploy to the implant** (run on the implant from the cloned repo root):

```bash
cp implant/api/app/routes/my_endpoint.py /opt/implant/api/app/routes/
systemctl restart implant-api
```

**3. Verify:**

```bash
curl -sk https://127.0.0.1:8443/my-endpoint | python3 -m json.tool
```

The new endpoint is immediately available to any skill script on the VPS.

---

## Adding a webhook notification

If a script or timer on the implant should push data to Discord automatically (without the operator asking), use the OpenClaw webhook.

**In the implant script:**

```bash
curl -sk -X POST "$OPENCLAW_WEBHOOK_URL" \
    -H "Authorization: Bearer $OPENCLAW_WEBHOOK_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"message\": \"my-alert: implant=${IMPLANT_WG_IP} key=value\",
        \"name\": \"my-skill\",
        \"sessionKey\": \"hook:my-alert\",
        \"deliver\": true,
        \"channel\": \"discord\",
        \"to\": \"${OPENCLAW_ALERT_CHANNEL_ID}\"
    }" >/dev/null 2>&1 &
wait
```

**In `SKILL.md`**, add a webhook section telling the agent how to format messages that start with your prefix:

```markdown
## Webhook alerts (my-alert)

Messages starting with `my-alert:` are automated push notifications.

When delivering to Discord, use this template:
🔔 **Alert** | Implant `{implant}` | {summary}
```

Each notification type should use its own `hook:<name>` session key to keep notification streams isolated. Allowed prefixes are configured in `/home/openclaw/.openclaw/openclaw.json` under `hooks.allowedSessionKeyPrefixes`.
