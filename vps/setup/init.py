#!/usr/bin/env python3
"""
VPS WireGuard & OpenClaw — Automated Setup
============================================
Provisions a VPS to run the OpenClaw AI assistant (replacing the legacy
discord.py bot) and a WireGuard server for PhantomPi implants.

Usage
-----
    sudo bash setup.sh                           # default config
    sudo bash setup.sh -c my.json                # custom config
    sudo bash setup.sh --debug                   # verbose output

The script reads deployment parameters from ``setup/init.json``
(or a user-supplied path).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import traceback

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR  = os.path.dirname(SETUP_DIR)

TOTAL_STEPS = 4

OC_USER      = "openclaw"
OC_HOME      = f"/home/{OC_USER}"
OPENCLAW_HOME = f"{OC_HOME}/.openclaw"
SKILLS_DIR   = os.path.join(OC_HOME, "skills")


# ═══════════════════════════════════════════════════════════════════════════
# Console UI
# ═══════════════════════════════════════════════════════════════════════════

class _C:
    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED = "\033[91m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
    CYAN = "\033[96m"; WHITE = "\033[97m"

if not sys.stdout.isatty():
    for _a in [a for a in dir(_C) if not a.startswith("_")]:
        setattr(_C, _a, "")


class UI:
    def __init__(self, debug_mode: bool = False):
        self._debug = debug_mode
        self._w = min(shutil.get_terminal_size().columns, 72)

    def banner(self):
        w = self._w
        print()
        print(f"{_C.CYAN}{_C.BOLD}{'=' * w}{_C.RESET}")
        title = "VPS WireGuard & OpenClaw — Automated Setup"
        print(f"{_C.WHITE}{_C.BOLD}{title.center(w)}{_C.RESET}")
        print(f"{_C.CYAN}{_C.BOLD}{'=' * w}{_C.RESET}")
        print()

    def step(self, num: int, total: int, title: str):
        w = self._w
        print()
        print(f"{_C.CYAN}{'-' * w}{_C.RESET}")
        print(f"{_C.CYAN}{_C.BOLD}  STEP {num}/{total} — {title}{_C.RESET}")
        print(f"{_C.CYAN}{'-' * w}{_C.RESET}")

    def info(self, msg):    print(f"  {_C.CYAN}[*]{_C.RESET} {msg}")
    def success(self, msg): print(f"  {_C.GREEN}[+]{_C.RESET} {msg}")
    def warning(self, msg): print(f"  {_C.YELLOW}[!]{_C.RESET} {msg}")
    def error(self, msg):   print(f"  {_C.RED}[-]{_C.RESET} {msg}")
    def skipped(self, msg): print(f"  {_C.YELLOW}[>]{_C.RESET} {_C.YELLOW}{msg}{_C.RESET}")

    def debug(self, msg):
        if self._debug:
            print(f"  {_C.DIM}[D] {msg}{_C.RESET}")

    def summary(self, skipped_items: list, failures: list):
        w = self._w
        print()
        print(f"{_C.CYAN}{'=' * w}{_C.RESET}")
        if failures:
            print(f"{_C.RED}{_C.BOLD}  FAILED — these steps need manual intervention:{_C.RESET}")
            print()
            for i, item in enumerate(failures, 1):
                print(f"  {_C.RED}{i}.{_C.RESET} {item}")
        if skipped_items:
            if failures:
                print()
            header = ("  SKIPPED — optional items still pending:"
                      if failures else
                      "  Setup complete — the following items need attention:")
            print(f"{_C.YELLOW}{_C.BOLD}{header}{_C.RESET}")
            print()
            for i, item in enumerate(skipped_items, 1):
                print(f"  {_C.YELLOW}{i}.{_C.RESET} {item}")
        if not failures and not skipped_items:
            print(f"{_C.GREEN}{_C.BOLD}  Setup complete — WireGuard & OpenClaw are ready!{_C.RESET}")
        print()
        print(f"{_C.CYAN}{'=' * w}{_C.RESET}")
        print()

    def run(self, cmd, *, check=True, capture=True, timeout=300):
        self.debug(f"$ {cmd}")
        try:
            r = subprocess.run(cmd, shell=True, capture_output=capture,
                               text=True, timeout=timeout)
            if capture and r.stdout and self._debug:
                for ln in r.stdout.strip().splitlines()[:5]:
                    self.debug(f"  stdout: {ln}")
            if r.returncode != 0:
                if capture and r.stderr and self._debug:
                    for ln in r.stderr.strip().splitlines()[:5]:
                        self.debug(f"  stderr: {ln}")
                if check:
                    raise RuntimeError(
                        f"Command exited {r.returncode}: {cmd}")
            return r
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Command timed out ({timeout}s): {cmd}")


# ═══════════════════════════════════════════════════════════════════════════
# Config helpers
# ═══════════════════════════════════════════════════════════════════════════

def _load(path: str) -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path) as fh:
        return json.load(fh)


def _get(cfg: dict, *keys, default=None):
    cur = cfg
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def _validate(cfg: dict) -> list[str]:
    w: list[str] = []
    if not _get(cfg, "openclaw", "anthropic_api_key"):
        w.append("openclaw.anthropic_api_key is empty — OpenClaw will NOT work")
    if not _get(cfg, "openclaw", "discord_bot_token"):
        w.append("openclaw.discord_bot_token is empty — Discord channel will NOT connect")
    if not _get(cfg, "openclaw", "discord_guild_id"):
        w.append("openclaw.discord_guild_id is empty — guild access will NOT work")
    peers = _get(cfg, "wireguard", "peers", default=[])
    has_peer = any(p.get("public_key") for p in peers)
    if not has_peer:
        w.append("wireguard.peers has no public_key entries — no peers will be added")
    return w


def _try(ui, label, fn, failures, debug):
    try:
        return fn()
    except Exception as exc:
        ui.error(f"{label}: {exc}")
        failures.append(f"{label} — {exc}")
        if debug:
            for line in traceback.format_exc().splitlines():
                ui.debug(line)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Step implementations
# ═══════════════════════════════════════════════════════════════════════════

# ── 1. System packages ───────────────────────────────────────────────────

def step_packages(ui: UI) -> None:
    pkgs = ["wireguard-tools", "python3-venv", "curl", "netcat-openbsd"]
    missing: list[str] = []
    for p in pkgs:
        r = ui.run(f"dpkg-query -W -f='${{Status}}' {p} 2>/dev/null "
                    "| grep -q 'install ok installed'", check=False)
        if r.returncode != 0:
            missing.append(p)

    if not missing:
        ui.success("All required packages already installed")
    else:
        ui.info(f"Installing: {', '.join(missing)} ...")
        ui.run("apt-get update -qq", timeout=120, check=False)
        ui.run(f"apt-get install -y -qq {' '.join(missing)}", timeout=120)
        ui.success("Packages installed")

    # Node.js v22+ (OpenClaw runtime dependency)
    r = ui.run("node --version 2>/dev/null | grep -qE '^v(2[2-9]|[3-9][0-9])'",
               check=False)
    if r.returncode == 0:
        ui.success("Node.js v22+ already installed")
    else:
        ui.info("Installing Node.js v22 (OpenClaw runtime) ...")
        ui.run("curl -fsSL https://deb.nodesource.com/setup_22.x | bash -",
               timeout=120)
        ui.run("apt-get install -y -qq nodejs", timeout=120)
        ui.success("Node.js installed")

    # Dedicated unprivileged user for running OpenClaw (no sudo, no shell)
    r = ui.run(f"id {OC_USER} 2>/dev/null", check=False)
    if r.returncode == 0:
        ui.success(f"User '{OC_USER}' already exists")
    else:
        ui.info(f"Creating dedicated user '{OC_USER}' ...")
        ui.run(
            f"useradd --system --create-home --home-dir {OC_HOME} "
            f"--shell /usr/sbin/nologin {OC_USER}"
        )
        ui.success(f"User '{OC_USER}' created (no sudo, no login shell)")
    ui.run(f"loginctl enable-linger {OC_USER} 2>/dev/null || true",
           check=False)


# ── 2. WireGuard server ─────────────────────────────────────────────────

def step_wireguard(cfg: dict, ui: UI, skipped: list) -> bool:
    wg_dir = "/etc/wireguard"
    os.makedirs(wg_dir, exist_ok=True)

    privkey_path = os.path.join(wg_dir, "private.key")
    pubkey_path  = os.path.join(wg_dir, "public.key")

    cfg_privkey = _get(cfg, "wireguard", "private_key", default="")

    if cfg_privkey:
        ui.info("Using server private key from configuration ...")
        with open(privkey_path, "w") as fh:
            fh.write(cfg_privkey.strip() + "\n")
        os.chmod(privkey_path, 0o600)
        ui.run(f"wg pubkey < {privkey_path} > {pubkey_path}")
        ui.success("WireGuard key pair set from configuration")
    elif not os.path.isfile(privkey_path):
        ui.info("Generating WireGuard server key pair ...")
        ui.run(f"wg genkey | tee {privkey_path} | wg pubkey > {pubkey_path}")
        os.chmod(privkey_path, 0o600)
        ui.success("WireGuard key pair generated")
    else:
        ui.success("WireGuard key pair already exists on disk")

    with open(pubkey_path) as fh:
        pubkey = fh.read().strip()
    ui.info(f"Server public key: {pubkey}")
    ui.info("  -> Put this key in each implant's init.json  "
            "wireguard.server_public_key")

    srv_addr    = _get(cfg, "wireguard", "server_address", default="10.8.0.1/24")
    listen_port = _get(cfg, "wireguard", "listen_port",    default=51820)
    peers       = _get(cfg, "wireguard", "peers",          default=[])

    with open(privkey_path) as fh:
        privkey = fh.read().strip()

    ui.info("Writing /etc/wireguard/wg0.conf ...")
    conf = (
        "[Interface]\n"
        f"PrivateKey = {privkey}\n"
        f"Address = {srv_addr}\n"
        f"ListenPort = {listen_port}\n"
        "PostUp = iptables -A FORWARD -i wg0 -o wg0 -j ACCEPT; "
        "iptables -A FORWARD -i wg0 -j ACCEPT\n"
        "PostDown = iptables -D FORWARD -i wg0 -o wg0 -j ACCEPT; "
        "iptables -D FORWARD -i wg0 -j ACCEPT\n"
    )

    peer_count = 0
    for peer in peers:
        pub = peer.get("public_key", "").strip()
        if not pub:
            continue
        ips = peer.get("allowed_ips", "").strip()
        if not ips:
            ui.warning(f"Peer {pub[:8]}… skipped — allowed_ips is empty")
            continue
        conf += f"\n[Peer]\n"
        conf += f"PublicKey = {pub}\n"
        conf += f"AllowedIPs = {ips}\n"
        peer_count += 1
        ui.success(f"Peer added: {ips}  ({pub[:12]}…)")

    if peer_count == 0:
        conf += "\n# No peers configured yet\n"
        skipped.append(
            "No WireGuard peers added — fill wireguard.peers entries "
            "with public keys and re-run setup"
        )

    conf_path = os.path.join(wg_dir, "wg0.conf")
    with open(conf_path, "w") as fh:
        fh.write(conf)
    os.chmod(conf_path, 0o600)

    ui.run("systemctl enable wg-quick@wg0.service 2>/dev/null || true",
           check=False)
    ui.run("systemctl restart wg-quick@wg0.service", check=False)
    ui.success("WireGuard server started")

    sysctl_conf = "/etc/sysctl.d/99-wireguard.conf"
    if not os.path.isfile(sysctl_conf):
        ui.info("Enabling IPv4 forwarding ...")
        with open(sysctl_conf, "w") as fh:
            fh.write("net.ipv4.ip_forward = 1\n")
        ui.run("sysctl -p /etc/sysctl.d/99-wireguard.conf", check=False)
        ui.success("IPv4 forwarding enabled")
    else:
        ui.success("IPv4 forwarding already configured")

    return peer_count > 0


# ── 3. Install OpenClaw & deploy skills ──────────────────────────────────

def step_openclaw(cfg: dict, ui: UI, skipped: list) -> None:
    """Install OpenClaw, deploy PhantomPi skills, write env/config."""

    # ── Write config FIRST (prevents interactive onboarding wizard) ──
    # OpenClaw's installer triggers an interactive setup wizard when it
    # finds no existing config.  Writing .env and openclaw.json before
    # installing means the wizard is skipped automatically.

    # ── Write ~/.openclaw/.env ───────────────────────────────────────
    os.makedirs(OPENCLAW_HOME, exist_ok=True)

    api_key      = _get(cfg, "openclaw", "anthropic_api_key", default="")
    bot_token    = _get(cfg, "openclaw", "discord_bot_token", default="")
    implant_ips  = _get(cfg, "openclaw", "implant_ips", default=[])
    implant_csv  = ",".join(implant_ips) if isinstance(implant_ips, list) else str(implant_ips)

    if not api_key:
        skipped.append(
            "openclaw.anthropic_api_key is empty — OpenClaw cannot "
            "run. Fill init.json and re-run setup."
        )
    if not bot_token:
        skipped.append(
            "openclaw.discord_bot_token is empty — Discord channel "
            "will not connect. Fill init.json and re-run setup."
        )

    # Hooks token — auto-generate if not provided
    hooks_token = _get(cfg, "openclaw", "hooks_token", default="")
    if not hooks_token:
        hooks_token = secrets.token_urlsafe(32)
        ui.info("Auto-generated OpenClaw hooks token")

    env_path = os.path.join(OPENCLAW_HOME, ".env")
    ui.info("Writing ~/.openclaw/.env ...")
    with open(env_path, "w") as fh:
        fh.write(f"ANTHROPIC_API_KEY={api_key}\n")
        fh.write(f"DISCORD_BOT_TOKEN={bot_token}\n")
        fh.write(f"IMPLANT_IPS={implant_csv}\n")
        fh.write(f"OPENCLAW_HOOKS_TOKEN={hooks_token}\n")
    os.chmod(env_path, 0o600)
    ui.success(".env written (permissions 600)")
    alert_channel_id = _get(cfg, "openclaw", "discord_alert_channel_id", default="")
    ui.info("Implant webhook config (copy to each implant's init.json or config.env):")
    ui.info(f'  OPENCLAW_WEBHOOK_URL="http://{_get(cfg, "wireguard", "server_address", default="10.8.0.1/24").split("/")[0]}:18789/hooks/agent"')
    ui.info(f'  OPENCLAW_WEBHOOK_TOKEN="{hooks_token}"')
    ui.info(f'  OPENCLAW_ALERT_CHANNEL_ID="{alert_channel_id}"  (numeric Discord channel ID)')
    if not alert_channel_id:
        ui.warning("discord_alert_channel_id is empty in init.json — fill it with the numeric Discord channel ID")

    # ── Write ~/.openclaw/openclaw.json ──────────────────────────────
    guild_id   = _get(cfg, "openclaw", "discord_guild_id", default="")
    admin_id   = _get(cfg, "openclaw", "discord_admin_user_id", default="")
    extra_users = _get(cfg, "openclaw", "discord_allowed_users", default=[])
    alert_ch   = _get(cfg, "openclaw", "discord_alert_channel", default="phantompi-alerts")
    chat_ch    = _get(cfg, "openclaw", "discord_chat_channel", default="phantompi-chat")

    # Build deduplicated user lists — admin always included
    all_users = [str(admin_id)] if admin_id else []
    for uid in extra_users:
        uid = str(uid)
        if uid and uid not in all_users:
            all_users.append(uid)
    allowed_users_str = ", ".join(f'"{u}"' for u in all_users)
    # DMs: admin only
    dm_users_str = f'"{admin_id}"' if admin_id else ""

    if not guild_id:
        skipped.append(
            "openclaw.discord_guild_id is empty — guild access will "
            "not work. Fill init.json and re-run setup."
        )

    # Derive WireGuard IP for gateway bind address
    r = ui.run("ip -4 addr show wg0 2>/dev/null | grep -oP 'inet \\K[0-9.]+'",
               check=False)
    wg_ip = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else ""
    if not wg_ip:
        # Fallback: parse from wg0.conf
        srv_addr = _get(cfg, "wireguard", "server_address", default="10.8.0.1/24")
        wg_ip = srv_addr.split("/")[0]
    ui.info(f"Gateway will bind to WireGuard IP: {wg_ip}")

    # Read template and substitute
    template_path = os.path.join(REPO_DIR, "openclaw", "openclaw.json.template")
    if os.path.isfile(template_path):
        with open(template_path) as fh:
            tmpl = fh.read()

        config_str = tmpl.replace("__GUILD_ID__", str(guild_id))
        config_str = config_str.replace("__ALLOWED_USERS__", allowed_users_str)
        config_str = config_str.replace("__DM_USERS__", dm_users_str)
        config_str = config_str.replace("__ALERT_CHANNEL_NAME__", alert_ch)
        config_str = config_str.replace("__CHAT_CHANNEL_NAME__", chat_ch)
        config_str = config_str.replace("__HOOKS_TOKEN__", hooks_token)
        config_str = config_str.replace("__GATEWAY_HOST__", wg_ip)

        config_path = os.path.join(OPENCLAW_HOME, "openclaw.json")
        ui.info("Writing ~/.openclaw/openclaw.json ...")
        with open(config_path, "w") as fh:
            fh.write(config_str)
        ui.success("OpenClaw config written")
    else:
        ui.warning("OpenClaw config template not found — create manually")

    # ── Install OpenClaw binary (config already in place — no wizard) ─
    r = ui.run("command -v openclaw 2>/dev/null", check=False)
    if not r.stdout.strip():
        ui.info("Installing OpenClaw ...")
        try:
            # Use npm directly — fully non-interactive, no installer wizard.
            # Node.js is already installed system-wide by step 1 so npm is
            # available. The binary lands in the global npm prefix
            # (/usr/local/bin/openclaw) which is in the search paths used
            # by both the binary locator below and the systemd service.
            ui.run("npm install -g openclaw", timeout=300)
            ui.success("OpenClaw installed")
        except RuntimeError:
            # Installer can take several minutes on a fresh VPS.
            # If it timed out but the binary landed, treat it as success.
            r2 = ui.run("command -v openclaw 2>/dev/null", check=False)
            if r2.stdout.strip():
                ui.warning(
                    "OpenClaw installer exceeded timeout but binary is present — continuing"
                )
            else:
                raise
    else:
        ui.success("OpenClaw already installed")

    # ── Fix npm package ownership ─────────────────────────────────────
    # `npm install -g` runs as root → installs to a root-owned directory.
    # OpenClaw installs plugin dependencies (discord, acpx, browser) the
    # first time it starts, which requires write access to that directory.
    # Give the openclaw service user ownership so those writes succeed.
    r_npm = ui.run("npm root -g 2>/dev/null", check=False)
    npm_root = r_npm.stdout.strip() if r_npm.returncode == 0 else ""
    if npm_root:
        oc_pkg = os.path.join(npm_root, "openclaw")
        if os.path.isdir(oc_pkg):
            ui.info(f"Setting ownership of {oc_pkg} to {OC_USER} ...")
            ui.run(f"chown -R {OC_USER}:{OC_USER} {oc_pkg}", check=False)
            ui.success(f"Plugin directory ownership fixed")

    # ── Deploy shared scripts to ~/scripts/ ──────────────────────────
    scripts_src = os.path.join(REPO_DIR, "openclaw", "scripts")
    scripts_dst = os.path.join(OC_HOME, "scripts")
    os.makedirs(scripts_dst, exist_ok=True)
    if os.path.isdir(scripts_src):
        ui.info(f"Deploying shared scripts to {scripts_dst} ...")
        for f in os.listdir(scripts_src):
            src_f = os.path.join(scripts_src, f)
            dst_f = os.path.join(scripts_dst, f)
            if os.path.isfile(src_f):
                shutil.copy2(src_f, dst_f)
                if f.endswith(".sh"):
                    os.chmod(dst_f, 0o755)
        ui.success("Shared scripts deployed")
    else:
        ui.warning(f"Shared scripts source not found at {scripts_src}")

    # ── Deploy skills to ~/skills/ ───────────────────────────────────
    skills_src = os.path.join(REPO_DIR, "openclaw", "skills")
    os.makedirs(SKILLS_DIR, exist_ok=True)

    if os.path.isdir(skills_src):
        ui.info(f"Deploying OpenClaw skills to {SKILLS_DIR} ...")
        for item in os.listdir(skills_src):
            s = os.path.join(skills_src, item)
            d = os.path.join(SKILLS_DIR, item)
            if os.path.isdir(s):
                if os.path.isdir(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d)
        for root, dirs, files in os.walk(SKILLS_DIR):
            for f in files:
                if f.endswith(".sh"):
                    os.chmod(os.path.join(root, f), 0o755)
        ui.success("Skills deployed")
    else:
        ui.warning(f"Skills source not found at {skills_src}")

    # ── Deploy workspace context files (SOUL.md etc.) ────────────────
    workspace_src = os.path.join(REPO_DIR, "openclaw", "workspace")
    workspace_dst = os.path.join(OPENCLAW_HOME, "workspace")
    os.makedirs(workspace_dst, exist_ok=True)
    if os.path.isdir(workspace_src):
        for f in os.listdir(workspace_src):
            src_f = os.path.join(workspace_src, f)
            dst_f = os.path.join(workspace_dst, f)
            if os.path.isfile(src_f):
                shutil.copy2(src_f, dst_f)
        ui.success("Workspace context files deployed (SOUL.md)")
    else:
        ui.warning("Workspace source not found — SOUL.md not deployed")

    # ── Fix ownership — everything under OC_HOME must belong to OC_USER
    ui.run(f"chown -R {OC_USER}:{OC_USER} {OC_HOME}", check=False)


# ── 4. Configure OpenClaw daemon ──────────────────────────────────────────

def step_daemon(cfg: dict, ui: UI, skipped: list) -> None:
    """Stop legacy bot and start the OpenClaw daemon."""

    # ── Stop old Discord bot if running ──────────────────────────────
    r = ui.run("systemctl is-active discord-bot.service 2>/dev/null",
               check=False)
    if r.returncode == 0:
        ui.info("Stopping legacy Discord bot ...")
        ui.run("systemctl stop discord-bot.service", check=False)
        ui.run("systemctl disable discord-bot.service", check=False)
        ui.run("rm -f /etc/systemd/system/discord-bot.service", check=False)
        ui.run("systemctl daemon-reload", check=False)
        ui.success("Legacy Discord bot stopped and disabled")

    # ── Create system-level systemd service ─────────────────────────
    # OpenClaw's built-in `daemon install` creates a user-level service
    # that requires a D-Bus login session.  Our openclaw user is a
    # system account with nologin shell — no session.  We write a
    # proper system unit that runs the gateway as the openclaw user.
    api_key = _get(cfg, "openclaw", "anthropic_api_key", default="")
    if not api_key:
        skipped.append(
            "OpenClaw gateway NOT started — API key missing. "
            "After filling init.json and re-run setup."
        )
        return

    ui.info(f"Installing OpenClaw gateway as system service ({OC_USER}) ...")

    # Locate the openclaw binary (npm global install → /usr/local/bin/openclaw)
    r = ui.run("command -v openclaw 2>/dev/null", check=False)
    oc_bin = r.stdout.strip() or "/usr/local/bin/openclaw"

    # Get WG IP for bind address (computed in step_openclaw)
    r = ui.run("ip -4 addr show wg0 2>/dev/null | grep -oP 'inet \\K[0-9.]+'",
               check=False)
    gw_host = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else ""
    if not gw_host:
        srv_addr = _get(cfg, "wireguard", "server_address", default="10.8.0.1/24")
        gw_host = srv_addr.split("/")[0]

    svc = (
        "[Unit]\n"
        "Description=OpenClaw Gateway\n"
        "After=network-online.target wg-quick@wg0.service\n"
        "Wants=network-online.target\n"
        "Requires=wg-quick@wg0.service\n"
        "\n"
        "[Service]\n"
        f"User={OC_USER}\n"
        f"Group={OC_USER}\n"
        f"WorkingDirectory={OC_HOME}\n"
        f"Environment=HOME={OC_HOME}\n"
        "Environment=NODE_ENV=production\n"
        "Environment=OPENCLAW_DISABLE_BONJOUR=1\n"
        f"EnvironmentFile={OPENCLAW_HOME}/.env\n"
        f"ExecStart={oc_bin} gateway --bind custom --port 18789\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    with open("/etc/systemd/system/openclaw-gateway.service", "w") as fh:
        fh.write(svc)

    ui.run("systemctl daemon-reload")
    ui.run("systemctl enable openclaw-gateway.service", check=False)
    ui.run("systemctl restart openclaw-gateway.service", check=False)
    ui.success("OpenClaw gateway started")

    ui.info(f"Webhook endpoint available at http://{gw_host}:18789/hooks/agent")
    ui.info("Implant scripts push events here — no cron polling needed")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vps-setup",
        description="VPS WireGuard & OpenClaw — Automated Setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  sudo bash setup.sh\n"
            "  sudo bash setup.sh -c /path/to/config.json\n"
            "  sudo bash setup.sh --debug\n"
        ),
    )
    parser.add_argument(
        "-c", "--config",
        default=os.path.join(SETUP_DIR, "init.json"),
        help="path to the JSON config file (default: setup/init.json)",
    )
    parser.add_argument(
        "-d", "--debug", action="store_true",
        help="enable verbose debug output",
    )
    args = parser.parse_args()

    ui = UI(debug_mode=args.debug)
    ui.banner()

    if os.geteuid() != 0:
        ui.error("This script must be run as root.  Use:  "
                 "sudo bash setup.sh")
        sys.exit(1)
    ui.success("Running as root")

    ui.info(f"Loading configuration from {args.config} ...")
    try:
        cfg = _load(args.config)
    except FileNotFoundError:
        ui.error(f"Configuration file not found: {args.config}")
        ui.info("Copy setup/init.json, fill in your values, and re-run.")
        sys.exit(1)
    except Exception as exc:
        ui.error(f"Failed to parse configuration: {exc}")
        sys.exit(1)
    ui.success("Configuration loaded")

    warnings = _validate(cfg)
    if warnings:
        ui.warning("Configuration has empty fields — affected features "
                    "will be skipped:")
        for w in warnings:
            ui.warning(f"  - {w}")

    skipped:  list[str] = []
    failures: list[str] = []

    # ── STEP 1 — System Packages ─────────────────────────────────────
    ui.step(1, TOTAL_STEPS, "System Packages")
    _try(ui, "Package installation",
         lambda: step_packages(ui), failures, args.debug)

    # ── STEP 2 — WireGuard Server ────────────────────────────────────
    ui.step(2, TOTAL_STEPS, "WireGuard Server")
    _try(ui, "WireGuard configuration",
         lambda: step_wireguard(cfg, ui, skipped), failures, args.debug)

    # ── STEP 3 — Install OpenClaw & Deploy Skills ────────────────────
    ui.step(3, TOTAL_STEPS, "Install OpenClaw & Deploy Skills")
    _try(ui, "OpenClaw deployment",
         lambda: step_openclaw(cfg, ui, skipped), failures, args.debug)

    # ── STEP 4 — Configure Daemon ───────────────────────────────────
    ui.step(4, TOTAL_STEPS, "Configure OpenClaw Daemon")
    _try(ui, "Daemon configuration",
         lambda: step_daemon(cfg, ui, skipped), failures, args.debug)

    # ── Summary ──────────────────────────────────────────────────────
    ui.summary(skipped, failures)

    if failures:
        ui.info("Some steps FAILED — fix the issues above then re-run:")
        print("    sudo bash setup.sh")
        print()
    elif skipped:
        ui.info("Complete the pending items listed above, then re-run:")
        print("    sudo bash setup.sh")
        print()
    else:
        ui.info("All done.  Verify with:")
        print("    wg show")
        print("    systemctl status openclaw-gateway.service")
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("  \033[93m[!]\033[0m Setup interrupted — re-run to resume:")
        print("      sudo bash setup.sh")
        print()
        sys.exit(130)
