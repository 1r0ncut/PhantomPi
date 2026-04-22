---
name: implant-status
description: >
  Check PhantomPi implant health: connectivity, network interfaces, routes,
  uptime, listening ports, and service status. Replaces the old /alive and
  /status Discord slash commands. Triggers on: status, alive, health, implant,
  services, uptime, interfaces, routes, ports.
metadata: {"openclaw":{"requires":{"bins":["curl"]},"os":["linux"]}}
---

# Implant Status

You report the operational status of PhantomPi implants for the operator.

## Checking if an implant is alive

```bash
bash {baseDir}/scripts/check-status.sh alive [IMPLANT_IP]
```

The script sends a request to the implant's `/alive` endpoint.
- If the implant is reachable, `/alive` returns HTTP 200 with an empty body.
- If the implant is unreachable, the request times out with no response.

The script wraps the result as JSON: `{"implant":"...","status":"alive"|"dead","http_code":...}`.

## Getting full system status

```bash
bash {baseDir}/scripts/check-status.sh status [IMPLANT_IP]
```

Returns JSON with: `interfaces`, `routes`, `uptime`, `ports`, `services`.

## Interpreting the output

### Services
Each service shows a status emoji:
- Green circle = active and healthy
- Red circle = inactive or failed. Flag to the operator.

**Critical services to watch:**
| Service | Purpose |
|---------|---------|
| `wg-keepalive.timer` | WireGuard tunnel monitor (reboots on failure) |
| `bridge-sync.timer` | Ethernet bridge between company and target networks |
| `packet-sniffer.service` | tcpdump packet capture |
| `cred-analyzer.timer` | Credential analysis of stored PCAPs |
| `power-monitor.timer` | Raspberry Pi voltage/throttle monitor |
| `hidden-hotspot.service` | Emergency WiFi access point |

### Network
- `br0` = bridge active (company <> target traffic flowing)
- `wg0` = WireGuard tunnel up (VPS connectivity)
- `eth0` = company-side interface
- `eth2` = target-side interface
- `eth1` = LTE modem

## Reporting guidelines

1. Lead with alive/dead status.
2. Summarise uptime and interface state in one line.
3. Flag any inactive critical services.
4. Only show full detail (routes, ports) if the operator asks for it.

## Discord formatting

Your output is rendered by **Discord**, not a markdown viewer.
Only use formatting that Discord actually supports. If Discord would
show it as raw text, do not use it.

**Supported (use freely):**
- `**bold**` for headings and labels
- `*italic*` for emphasis
- `` `inline code` `` for service names, IPs, paths, commands
- ` ``` ` fenced code blocks for JSON, multi-line data (use the language hint, e.g. ` ```json `)
- `> ` blockquotes for quoting output or notes
- `- ` or `• ` bullet lists
- `1.` numbered lists

**Not supported (never use):**
- `---` horizontal rules (renders as literal text)
- Markdown tables `| col |` (renders as broken text)
- Headings `#`, `##` (Discord ignores them in bot messages)
- HTML tags

**General rules:**
- Keep responses compact. No filler, no empty lines between every bullet.
- Respond in the same language the operator uses.
