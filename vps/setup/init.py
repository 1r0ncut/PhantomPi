#!/usr/bin/env python3
"""
VPS WireGuard & Discord Bot — Automated Setup
===================================
Provisions a VPS to run the Discord C2 bot and WireGuard server
for the PhantomPi implant.

Usage
-----
    sudo bash setup.sh                           # default config
    sudo bash setup.sh -c my.json                # custom config
    sudo bash setup.sh --debug                   # verbose output

The script reads deployment parameters from ``setup/init.json``
(or a user-supplied path).  Fields left empty are skipped; a final
summary reminds the operator what still needs attention.
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
# Path setup — works no matter where the repo was cloned
# ---------------------------------------------------------------------------
SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR  = os.path.dirname(SETUP_DIR)

TOTAL_STEPS = 4

# Deploy root (mirrors implant-side /opt/implant structure)
IMPLANT_DIR  = "/opt/implant"
DISCORD_DIR  = os.path.join(IMPLANT_DIR, "discord")
SERVICES_DIR = os.path.join(IMPLANT_DIR, "services")


# ═══════════════════════════════════════════════════════════════════════════
# Console UI  (lightweight copy of PhantomPi's modules/ui.py)
# ═══════════════════════════════════════════════════════════════════════════

class _C:
    """ANSI colours — stripped when stdout is not a TTY."""
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

    # -- Banner ------------------------------------------------------------
    def banner(self):
        w = self._w
        print()
        print(f"{_C.CYAN}{_C.BOLD}{'=' * w}{_C.RESET}")
        title = "VPS WireGuard & Discord Bot — Automated Setup"
        print(f"{_C.WHITE}{_C.BOLD}{title.center(w)}{_C.RESET}")
        print(f"{_C.CYAN}{_C.BOLD}{'=' * w}{_C.RESET}")
        print()

    def step(self, num: int, total: int, title: str):
        w = self._w
        print()
        print(f"{_C.CYAN}{'-' * w}{_C.RESET}")
        print(f"{_C.CYAN}{_C.BOLD}  STEP {num}/{total} — {title}{_C.RESET}")
        print(f"{_C.CYAN}{'-' * w}{_C.RESET}")

    # -- Messages ----------------------------------------------------------
    def info(self, msg):    print(f"  {_C.CYAN}[*]{_C.RESET} {msg}")
    def success(self, msg): print(f"  {_C.GREEN}[+]{_C.RESET} {msg}")
    def warning(self, msg): print(f"  {_C.YELLOW}[!]{_C.RESET} {msg}")
    def error(self, msg):   print(f"  {_C.RED}[-]{_C.RESET} {msg}")
    def skipped(self, msg): print(f"  {_C.YELLOW}[>]{_C.RESET} {_C.YELLOW}{msg}{_C.RESET}")

    def debug(self, msg):
        if self._debug:
            print(f"  {_C.DIM}[D] {msg}{_C.RESET}")

    # -- Summary -----------------------------------------------------------
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
            print(f"{_C.GREEN}{_C.BOLD}  Setup complete — WireGuard & Discord bot are ready!{_C.RESET}")
        print()
        print(f"{_C.CYAN}{'=' * w}{_C.RESET}")
        print()

    # -- Shell runner ------------------------------------------------------
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
    if not _get(cfg, "discord", "bot_token"):
        w.append("discord.bot_token is empty — bot will NOT start")
    if not _get(cfg, "discord", "guild_id"):
        w.append("discord.guild_id is empty — slash commands will NOT sync")
    peers = _get(cfg, "wireguard", "peers", default=[])
    has_peer = any(p.get("public_key") for p in peers)
    if not has_peer:
        w.append(
            "wireguard.peers has no public_key entries — no WireGuard "
            "peers will be added (fill after running PhantomPi setup)"
        )
    return w


# ═══════════════════════════════════════════════════════════════════════════
# Fail-safe runner
# ═══════════════════════════════════════════════════════════════════════════

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

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------

def step_packages(ui: UI) -> None:
    """Install required APT packages (idempotent)."""
    pkgs = ["wireguard-tools", "python3-venv"]
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


# ---------------------------------------------------------------------------
# 2. WireGuard server
# ---------------------------------------------------------------------------

def step_wireguard(cfg: dict, ui: UI, skipped: list) -> bool:
    """Configure WireGuard server interface and peer(s)."""
    wg_dir = "/etc/wireguard"
    os.makedirs(wg_dir, exist_ok=True)

    privkey_path = os.path.join(wg_dir, "private.key")
    pubkey_path  = os.path.join(wg_dir, "public.key")

    # ── Key handling ──────────────────────────────────────────────────
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

    # ── wg0.conf ──────────────────────────────────────────────────────
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

    # ── Peers ─────────────────────────────────────────────────────────
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

    # Enable at boot
    ui.run("systemctl enable wg-quick@wg0.service 2>/dev/null || true",
           check=False)

    # Always restart to guarantee the on-disk config is active
    ui.run("systemctl restart wg-quick@wg0.service", check=False)
    ui.success("WireGuard server started")

    # ── IP forwarding (for implant internet access via VPS) ──────────
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


# ---------------------------------------------------------------------------
# 3. Deploy Discord bot
# ---------------------------------------------------------------------------

def step_deploy(cfg: dict, ui: UI, skipped: list) -> None:
    """Copy bot + service files, create venv, install deps, write config."""
    discord_src  = os.path.join(REPO_DIR, "discord")
    services_src = os.path.join(REPO_DIR, "services")
    venv_dir     = os.path.join(DISCORD_DIR, "venv")
    logs_dir     = os.path.join(DISCORD_DIR, "logs")

    # ── Copy bot files → /opt/implant/discord/ ────────────────────────
    if not os.path.isdir(discord_src):
        raise FileNotFoundError(
            f"Bot source not found at {discord_src} — "
            f"run setup from the vps/ directory")

    ui.info(f"Deploying bot files to {DISCORD_DIR} ...")
    os.makedirs(DISCORD_DIR, exist_ok=True)

    # Copy everything except venv, logs, __pycache__
    for item in os.listdir(discord_src):
        if item in ("venv", "logs", "__pycache__"):
            continue
        src = os.path.join(discord_src, item)
        dst = os.path.join(DISCORD_DIR, item)
        if os.path.isdir(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    ui.success("Bot files deployed")

    # ── Copy service files → /opt/implant/services/ ───────────────────
    os.makedirs(SERVICES_DIR, exist_ok=True)
    if os.path.isdir(services_src):
        for item in os.listdir(services_src):
            src = os.path.join(services_src, item)
            dst = os.path.join(SERVICES_DIR, item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
        ui.success(f"Service files deployed to {SERVICES_DIR}")

    # ── Logs directory ────────────────────────────────────────────────
    os.makedirs(logs_dir, exist_ok=True)
    ui.success("Logs directory ready")

    # ── Python virtual environment ────────────────────────────────────
    if not os.path.isdir(venv_dir):
        ui.info("Creating Python virtual environment ...")
        ui.run(f"python3 -m venv {venv_dir}", timeout=60)
        ui.run(f"{venv_dir}/bin/pip install --upgrade pip -q", timeout=60)
        ui.success("Virtual environment created")
    else:
        ui.success("Virtual environment already exists")

    # Install / update dependencies
    req_file = os.path.join(DISCORD_DIR, "requirements.txt")
    if os.path.isfile(req_file):
        ui.info("Installing Python dependencies ...")
        ui.run(f"{venv_dir}/bin/pip install -r {req_file} -q", timeout=120)
        ui.success("Dependencies installed")

    # ── Write config.py with actual credentials ──────────────────────
    token    = _get(cfg, "discord", "bot_token", default="")
    guild_id = _get(cfg, "discord", "guild_id",  default="")

    if not token:
        skipped.append(
            "discord.bot_token is empty — bot will not start. "
            "Fill init.json and re-run setup."
        )
    if not guild_id:
        skipped.append(
            "discord.guild_id is empty — slash commands will not sync. "
            "Fill init.json and re-run setup."
        )

    ui.info("Writing config.py with credentials ...")
    config_py = os.path.join(DISCORD_DIR, "config.py")
    with open(config_py, "w") as fh:
        fh.write(
            f'DISCORD_TOKEN = "{token}"\n'
            f'GUILD_ID = {guild_id if guild_id else "0"}\n'
        )
    os.chmod(config_py, 0o600)
    ui.success("config.py written (permissions 600)")



# ---------------------------------------------------------------------------
# 4. Systemd service
# ---------------------------------------------------------------------------

def step_systemd(cfg: dict, ui: UI) -> None:
    """Write service file to /opt/implant/services/, symlink, enable."""
    venv_dir = os.path.join(DISCORD_DIR, "venv")
    svc_name = "discord-bot.service"
    svc_src  = os.path.join(SERVICES_DIR, svc_name)
    svc_link = os.path.join("/etc/systemd/system", svc_name)

    # ── Write service unit to /opt/implant/services/ ──────────────────
    ui.info(f"Writing {svc_src} ...")
    os.makedirs(SERVICES_DIR, exist_ok=True)

    svc = (
        "[Unit]\n"
        "Description=Discord RedTeam Implant Bot\n"
        "After=network-online.target wg-quick@wg0.service\n"
        "Wants=network-online.target wg-quick@wg0.service\n"
        "\n"
        "[Service]\n"
        f"WorkingDirectory={DISCORD_DIR}\n"
        f"ExecStart={venv_dir}/bin/python3 {DISCORD_DIR}/bot.py\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "User=root\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    with open(svc_src, "w") as fh:
        fh.write(svc)

    # ── Symlink into /etc/systemd/system/ ─────────────────────────────
    if os.path.islink(svc_link) or os.path.exists(svc_link):
        os.remove(svc_link)
    os.symlink(svc_src, svc_link)
    ui.success(f"{svc_name} -> {svc_src}")

    ui.run("systemctl daemon-reload")
    ui.run("systemctl enable discord-bot.service 2>/dev/null || true",
           check=False)

    # Restart if already running (picks up config changes)
    r = ui.run("systemctl is-active discord-bot.service 2>/dev/null",
               check=False)
    if r.returncode == 0:
        ui.run("systemctl restart discord-bot.service", check=False)
        ui.success("discord-bot.service restarted with new config")
    else:
        # Only start if token is present
        token = _get(cfg, "discord", "bot_token", default="")
        if token:
            ui.run("systemctl start discord-bot.service", check=False)
            ui.success("discord-bot.service started")
        else:
            ui.warning("discord-bot.service enabled but NOT started "
                       "(bot_token is empty)")

    ui.success("discord-bot.service installed and enabled at boot")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vps-setup",
        description="VPS WireGuard & Discord Bot — Automated Setup",
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

    # ── Pre-flight ────────────────────────────────────────────────────
    if os.geteuid() != 0:
        ui.error("This script must be run as root.  Use:  "
                 "sudo bash setup.sh")
        sys.exit(1)
    ui.success("Running as root")

    # ── Load config ───────────────────────────────────────────────────
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

    # ══════════════════════════════════════════════════════════════════
    #  STEP 1 — System Packages
    # ══════════════════════════════════════════════════════════════════
    ui.step(1, TOTAL_STEPS, "System Packages")
    _try(ui, "Package installation",
         lambda: step_packages(ui), failures, args.debug)

    # ══════════════════════════════════════════════════════════════════
    #  STEP 2 — WireGuard Server
    # ══════════════════════════════════════════════════════════════════
    ui.step(2, TOTAL_STEPS, "WireGuard Server")
    _try(ui, "WireGuard configuration",
         lambda: step_wireguard(cfg, ui, skipped), failures, args.debug)

    # ══════════════════════════════════════════════════════════════════
    #  STEP 3 — Deploy Discord Bot
    # ══════════════════════════════════════════════════════════════════
    ui.step(3, TOTAL_STEPS, "Deploy Discord Bot")
    _try(ui, "Bot deployment",
         lambda: step_deploy(cfg, ui, skipped), failures, args.debug)

    # ══════════════════════════════════════════════════════════════════
    #  STEP 4 — Systemd Service
    # ══════════════════════════════════════════════════════════════════
    ui.step(4, TOTAL_STEPS, "Systemd Service")
    _try(ui, "Service configuration",
         lambda: step_systemd(cfg, ui), failures, args.debug)

    # ══════════════════════════════════════════════════════════════════
    #  Summary
    # ══════════════════════════════════════════════════════════════════
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
        print("    systemctl status discord-bot")
        print()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("  \033[93m[!]\033[0m Setup interrupted — re-run to resume:")
        print("      sudo bash setup.sh")
        print()
        sys.exit(130)
