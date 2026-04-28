---
name: implant-status
description: >
  Check PhantomPi implant health: connectivity, network interfaces, routes,
  uptime, listening ports, and service status. Replaces the old /alive and
  /status Discord slash commands. Triggers on: status, alive, health, implant,
  services, uptime, interfaces, routes, ports.
metadata: {"openclaw":{"requires":{"bins":["curl","nc"]},"os":["linux"]}}
---

# Implant Status

You report the operational status of PhantomPi implants for the operator.

## Querying implant status

```bash
bash /home/openclaw/scripts/query-implant.sh /status [IMPLANT_IPS]
```

Omit the IP argument for general queries — the script reads `$IMPLANT_IPS` and checks all implants automatically.
Pass a specific IP for targeted queries.

The script performs a TCP alive check on port 8443 before querying. Output is a JSON object keyed by implant IP:

```json
{
  "10.8.0.3": {"alive": true,  "data": {...}},
  "10.8.0.4": {"alive": false, "data": null}
}
```

## Interpreting the output

### Alive check
- `alive: false` — implant is unreachable. Report as dead, do not proceed.
- `alive: true` — implant responded; read `data` for full status.

### Interfaces (`data.interfaces`)
List of `{name, state, addresses}` objects.
- `wg0` UP — WireGuard tunnel active (C2 connectivity)
- `br0` UP — bridge active (inline interception mode)
- `eth0` / `eth2` UP — company-side / target-side cables connected
- `eth1` UP — LTE modem connected
- `wlan0` UP — emergency hotspot active

### Services (`data.services`)
List of `{name, active}` objects. Flag any critical service where `active` is `false`:

| Service | Purpose |
|---------|---------|
| `wg-keepalive.timer` | WireGuard tunnel monitor |
| `bridge-sync.timer` | Ethernet bridge lifecycle |
| `packet-sniffer.service` | tcpdump packet capture |
| `cred-analyzer.timer` | Credential analysis of PCAPs |
| `power-monitor.timer` | Raspberry Pi voltage/throttle monitor |
| `hidden-hotspot.service` | Emergency WiFi access point |

### Uptime
`data.uptime` — plain string from `uptime -p`.

## Reporting guidelines

1. Lead with alive/dead status for each implant.
2. Summarise uptime and interface state in one line.
3. Flag any critical service where `active` is `false`.
4. Add 🟢 / 🔴 emojis when formatting services for Discord.
5. Only show full detail (routes, ports) if the operator asks for it.
