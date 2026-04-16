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

OPENCLAW_DIR = "/opt/openclaw"
SKILLS_DIR   = os.path.join(OPENCLAW_DIR, "skills")
OPENCLAW_HOME = os.path.expanduser("~/.openclaw")


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
    pkgs = ["wireguard-tools", "python3-venv", "curl"]
    missing: list[str] = []
    for p in pkgs:
        r = ui.run(f"dpkg-query -W -f='${{Status}}' {p} 2>/dev/null "
                    "| grep -q 'install ok installed'", check=False)
        if r.returncode != 0:
            missing.append(p)

    if not missing:
        ui.success("All required packages already installed")
        return

    ui.info(f"Installing: {', '.join(missing)} ...")
    ui.run("apt-get update -qq", timeout=120, check=False)
    ui.run(f"apt-get install -y -qq {' '.join(missing)}", timeout=120)
    ui.success("Packages installed")


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

    # ── Install OpenClaw binary ──────────────────────────────────────
    r = ui.run("command -v openclaw 2>/dev/null", check=False)
    if r.returncode != 0:
        ui.info("Installing OpenClaw ...")
        ui.run(
            "curl -fsSL https://openclaw.ai/install.sh | bash",
            timeout=180,
        )
        ui.success("OpenClaw installed")
    else:
        ui.success("OpenClaw already installed")

    # ── Deploy skills to /opt/openclaw/skills/ ───────────────────────
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
        # Make skill scripts executable
        for root, dirs, files in os.walk(SKILLS_DIR):
            for f in files:
                if f.endswith(".sh"):
                    path = os.path.join(root, f)
                    os.chmod(path, 0o755)
        ui.success("Skills deployed")
    else:
        ui.warning(f"Skills source not found at {skills_src}")

    # ── Write ~/.openclaw/.env ───────────────────────────────────────
    os.makedirs(OPENCLAW_HOME, exist_ok=True)

    api_key   = _get(cfg, "openclaw", "anthropic_api_key", default="")
    bot_token = _get(cfg, "openclaw", "discord_bot_token", default="")
    implant   = _get(cfg, "openclaw", "implant_ip", default="10.8.0.3")

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

    env_path = os.path.join(OPENCLAW_HOME, ".env")
    ui.info("Writing ~/.openclaw/.env ...")
    with open(env_path, "w") as fh:
        fh.write(f"ANTHROPIC_API_KEY={api_key}\n")
        fh.write(f"DISCORD_BOT_TOKEN={bot_token}\n")
        fh.write(f"IMPLANT_IP={implant}\n")
    os.chmod(env_path, 0o600)
    ui.success(".env written (permissions 600)")

    # ── Write ~/.openclaw/openclaw.json ──────────────────────────────
    guild_id   = _get(cfg, "openclaw", "discord_guild_id", default="")
    admin_id   = _get(cfg, "openclaw", "discord_admin_user_id", default="")
    alert_ch   = _get(cfg, "openclaw", "discord_alert_channel", default="phantompi-alerts")
    chat_ch    = _get(cfg, "openclaw", "discord_chat_channel", default="phantompi-chat")

    if not guild_id:
        skipped.append(
            "openclaw.discord_guild_id is empty — guild access will "
            "not work. Fill init.json and re-run setup."
        )

    # Read template and substitute
    template_path = os.path.join(REPO_DIR, "openclaw", "openclaw.json.template")
    if os.path.isfile(template_path):
        with open(template_path) as fh:
            tmpl = fh.read()

        config_str = tmpl.replace("__GUILD_ID__", str(guild_id))
        config_str = config_str.replace("__ADMIN_USER_ID__", str(admin_id))
        config_str = config_str.replace("__ALERT_CHANNEL_NAME__", alert_ch)
        config_str = config_str.replace("__CHAT_CHANNEL_NAME__", chat_ch)

        config_path = os.path.join(OPENCLAW_HOME, "openclaw.json")
        ui.info("Writing ~/.openclaw/openclaw.json ...")
        with open(config_path, "w") as fh:
            fh.write(config_str)
        ui.success("OpenClaw config written")
    else:
        ui.warning("OpenClaw config template not found — create manually")

    # ── Also deploy skills to ~/.openclaw/skills/ as fallback ────────
    user_skills = os.path.join(OPENCLAW_HOME, "skills")
    os.makedirs(user_skills, exist_ok=True)
    if os.path.isdir(skills_src):
        for item in os.listdir(skills_src):
            s = os.path.join(skills_src, item)
            d = os.path.join(user_skills, item)
            if os.path.isdir(s):
                if os.path.isdir(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d)
        for root, dirs, files in os.walk(user_skills):
            for f in files:
                if f.endswith(".sh"):
                    os.chmod(os.path.join(root, f), 0o755)
        ui.success("Skills also deployed to ~/.openclaw/skills/")


# ── 4. Configure OpenClaw daemon & cron ──────────────────────────────────

def step_daemon(cfg: dict, ui: UI, skipped: list) -> None:
    """Install OpenClaw daemon and set up the cred-sniffer cron job."""

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

    # ── Install daemon ───────────────────────────────────────────────
    r = ui.run("openclaw gateway status 2>/dev/null", check=False)
    if r.returncode == 0:
        ui.success("OpenClaw gateway already running")
    else:
        api_key = _get(cfg, "openclaw", "anthropic_api_key", default="")
        if api_key:
            ui.info("Starting OpenClaw gateway ...")
            # Install the daemon (launchd on macOS, systemd on Linux)
            ui.run("openclaw daemon install 2>/dev/null || true",
                   check=False, timeout=30)
            ui.run("openclaw daemon start 2>/dev/null || true",
                   check=False, timeout=30)
            ui.success("OpenClaw gateway started")
        else:
            skipped.append(
                "OpenClaw gateway NOT started — API key missing. "
                "After filling init.json and re-running setup, start with: "
                "openclaw daemon start"
            )

    # ── Set up cred-sniffer cron job ─────────────────────────────────
    implant_ip = _get(cfg, "openclaw", "implant_ip", default="10.8.0.3")
    alert_ch   = _get(cfg, "openclaw", "discord_alert_channel",
                       default="phantompi-alerts")

    # Check if cron job already exists
    r = ui.run("openclaw cron list 2>/dev/null | grep -q cred-sniffer",
               check=False)
    if r.returncode == 0:
        ui.success("cred-sniffer cron job already exists")
    else:
        api_key = _get(cfg, "openclaw", "anthropic_api_key", default="")
        if api_key:
            ui.info("Creating cred-sniffer cron job (every 60s) ...")
            ui.run(
                f"openclaw cron add "
                f"--name cred-sniffer "
                f"--every 1m "
                f"--session isolated "
                f'--message "Run the cred-sniffer skill: use the '
                f"check-findings.sh script to fetch credential findings "
                f"from implant {implant_ip}. If there are new findings "
                f'since the last check, summarise them." '
                f"--tools exec,read "
                f"--announce "
                f"--channel discord",
                check=False, timeout=30,
            )
            ui.success("cred-sniffer cron job created")
        else:
            skipped.append(
                "cred-sniffer cron job NOT created — API key missing. "
                "Create manually after setup with:\n"
                "    openclaw cron add --name cred-sniffer --every 1m "
                "--session isolated --message '...' --tools exec,read "
                "--announce --channel discord"
            )


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

    # ── STEP 4 — Configure Daemon & Cron ─────────────────────────────
    ui.step(4, TOTAL_STEPS, "Configure OpenClaw Daemon & Cron")
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
        print("    openclaw gateway status")
        print("    openclaw cron list")
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
