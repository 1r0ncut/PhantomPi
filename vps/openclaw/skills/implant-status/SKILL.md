---
name: implant-status
description: >
  Check PhantomPi implant health: connectivity, interfaces, services, uptime, ports.
  Triggers on: status, alive, health, implant, services, uptime, interfaces, ports.
metadata: {"openclaw":{"requires":{"bins":["curl","nc"]},"os":["linux"]}}
---

# Implant Status

## Querying implants

**Reachability only:**
```bash
bash /home/openclaw/scripts/query-implant.sh --alive [IMPLANT_IPS]
```

**Full status:**
```bash
bash /home/openclaw/scripts/query-implant.sh /status [IMPLANT_IPS]
```

Omit IP for general queries; script reads `$IMPLANT_IPS` automatically. Output is keyed by implant IP: `{"10.8.0.3": {"alive": true, "data": {...}}, ...}`

## Interpreting the output

- `alive: false`: unreachable, report dead.
- `alive: true`: read `data` for full status.
- `data.interfaces`: list of `{name, state, addresses}` — use SOUL.md for interpretation.
- `data.services`: list of `{name, active}` — use SOUL.md to determine which inactive services are problems.
- `data.uptime`: plain string from `uptime -p`.

## Reporting guidelines

1. Lead with alive/dead for each implant.
2. Summarise uptime and interface state in one line.
3. Flag critical services where `active` is `false` with 🔴, healthy with 🟢.
4. Show routes/ports only if the operator asks.
