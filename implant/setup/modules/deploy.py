"""
PhantomPi Setup — File Deployment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Copy implant runtime files from the repo to ``/opt/implant/``
* Create every log directory the implant expects
* Set executable permissions on shell scripts
* Generate ``/opt/implant/config.env`` from the JSON configuration
* Create ``/usr/local/bin/`` symlinks for operator helper tools
"""

from __future__ import annotations

import os
import shutil
import stat

from .config import get, get_implant_ip
from .ui import UI


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Log sub-directories under /opt/implant/logs/
_LOG_DIRS = [
    "bridge-sync",
    "bruteshark",
    "hidden-hotspot",
    "openclaw",
    "packet-sniffer",
    "power-monitor",
    "spoof-target",
    "wg-keepalive",
]

# Scripts that must be executable
_EXEC_SCRIPTS = [
    "bridge-sync.sh",
    "hidden-hotspot.sh",
    "modem-config.sh",
    "packet-sniffer.sh",
    "power-monitor.sh",
    "spoof-target.sh",
    "wg-keepalive.sh",
]

# Symlinks in /usr/local/bin/ for quick operator access
_HELPER_LINKS = {
    "hidden-hotspot": "/opt/implant/scripts/hidden-hotspot.sh",
    "modem-config":   "/opt/implant/scripts/modem-config.sh",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def deploy_files(repo_dir: str, ui: UI) -> None:
    """
    Copy implant runtime files from the cloned repository into
    ``/opt/implant/``.  Existing files are overwritten; files already on
    disk that are *not* in the repo (e.g. logs, certs) are preserved.

    The repo layout has runtime directories (discord/, scripts/, services/,
    timers/, wittypi/, config.env) directly under ``implant/``.  The
    ``setup/`` directory and ``setup.sh`` are excluded — they are only
    needed on the operator's machine, not on the target device.
    """
    # Items that live in the repo but should NOT be deployed to /opt/implant/
    _SKIP = {"setup", "setup.sh", "logs", "__pycache__", ".git"}

    src = repo_dir
    dst = "/opt/implant"

    if not os.path.isdir(src):
        raise RuntimeError(f"Source directory not found: {src}")

    ui.info("Copying implant files to /opt/implant/ ...")
    os.makedirs(dst, exist_ok=True)

    for item in os.listdir(src):
        if item in _SKIP:
            continue
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)

    ui.success("Implant files deployed")

    # ── Patch wg-keepalive.timer interval ─────────────────────────────────
    # The repo ships OnUnitActiveSec=1min, but the safe interval per the
    # documentation is 1h.  At 1min the keepalive script (which reboots on
    # failure) runs far too aggressively.
    timer_path = "/opt/implant/timers/wg-keepalive.timer"
    if os.path.isfile(timer_path):
        with open(timer_path, "r") as fh:
            content = fh.read()
        patched = content.replace("OnUnitActiveSec=1min", "OnUnitActiveSec=1h")
        if patched != content:
            with open(timer_path, "w") as fh:
                fh.write(patched)
            ui.success("wg-keepalive.timer interval corrected to 1h")


def create_log_dirs(ui: UI) -> None:
    """Create every log directory the implant services expect."""
    ui.info("Creating log directories ...")
    for name in _LOG_DIRS:
        os.makedirs(f"/opt/implant/logs/{name}", exist_ok=True)
    # Discord API server log
    os.makedirs("/opt/implant/discord/logs", exist_ok=True)
    ui.success("Log directories created")


def set_permissions(ui: UI) -> None:
    """Ensure shell scripts under ``/opt/implant/scripts/`` are executable."""
    ui.info("Setting script permissions ...")
    scripts_dir = "/opt/implant/scripts"
    for script in _EXEC_SCRIPTS:
        path = os.path.join(scripts_dir, script)
        if os.path.isfile(path):
            st = os.stat(path)
            os.chmod(
                path,
                st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
            )
    ui.success("Permissions set")


def create_helper_symlinks(ui: UI) -> None:
    """
    Create ``/usr/local/bin/`` symlinks so operators can call helper
    tools (``modem-config``, ``hidden-hotspot``) from any directory.
    """
    ui.info("Creating helper-tool symlinks ...")
    for name, target in _HELPER_LINKS.items():
        link = f"/usr/local/bin/{name}"
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        if os.path.isfile(target):
            os.symlink(target, link)
            ui.debug(f"  {link} -> {target}")
    ui.success("Helper symlinks created")


# ---------------------------------------------------------------------------
# config.env generation
# ---------------------------------------------------------------------------

def generate_config_env(config: dict, ui: UI) -> None:
    """
    Render ``/opt/implant/config.env`` from values in the JSON config.
    Every implant script sources this file, so it acts as the single
    source of truth for runtime parameters.
    """
    ui.info("Generating /opt/implant/config.env ...")

    implant_ip  = get_implant_ip(config)
    iface_tg    = get(config, "network", "iface_target", default="eth2")

    hidden_flag = "yes" if get(config, "hotspot", "hidden", default=True) else "no"
    notify_flag = "true" if get(config, "discord", "notify", default=True) else "false"

    lines = [
        "# === PhantomPi Implant Configuration ===",
        "# Auto-generated by setup/init.py — edit init.json and re-run to update.",
        "",
        "# --- Network Interfaces & Bridge ---",
        f'IFACE_COMPANY="{get(config, "network", "iface_company", default="eth0")}"',
        f'IFACE_TARGET="{iface_tg}"',
        f'VETH_IN="{get(config, "network", "veth_in", default="veth0")}"',
        f'VETH_OUT="{get(config, "network", "veth_out", default="veth1")}"',
        f'BRIDGE="{get(config, "network", "bridge", default="br0")}"',
        "",
        "# --- Implant WireGuard IP ---",
        f'IMPLANT_WG_IP="{implant_ip}"',
        "",
        "# --- Bridge Sync ---",
        'BRIDGE_SYNC_LOG="/opt/implant/logs/bridge-sync/bridge-sync.log"',
        f'BRIDGE_SYNC_DISCORD_WEBHOOK_URL="{get(config, "discord", "bridge_sync_webhook_url", default="")}"',
        f'DISCORD_NOTIFY={notify_flag}',
        "",
        "# --- BruteShark ---",
        'BRUTESHARK_LOG="/opt/implant/logs/bruteshark/cli-output.log"',
        'BRUTESHARK_CREDS="/opt/implant/logs/bruteshark/credentials.json"',
        f'BRUTESHARK_DISCORD_WEBHOOK_URL="{get(config, "discord", "bruteshark_webhook_url", default="")}"',
        "",
        "# --- Hidden Hotspot ---",
        "# To apply changes run:  hidden-hotspot update",
        f'HOTSPOT_SSID="{get(config, "hotspot", "ssid", default="berry_ap")}"',
        f'HOTSPOT_PSK="{get(config, "hotspot", "psk", default="")}"',
        f'HOTSPOT_IFACE="{get(config, "hotspot", "interface", default="wlan0")}"',
        f'HOTSPOT_HIDDEN="{hidden_flag}"',
        "",
        "# --- Power Monitor ---",
        'POWER_MONITOR_LOG="/opt/implant/logs/power-monitor/power-monitor.log"',
        "",
        "# --- Packet Sniffer ---",
        'SNIFFER_LOG_DIR="/opt/implant/logs/packet-sniffer"',
        f'SNIFFER_INTERFACE="{iface_tg}"',
        f'SNIFFER_FILE_PREFIX="{get(config, "sniffer", "file_prefix", default="capture")}"',
        f'SNIFFER_MAX_FILE_SIZE_MB={get(config, "sniffer", "max_file_size_mb", default=200)}',
        f'SNIFFER_MAX_TOTAL_FILES={get(config, "sniffer", "max_total_files", default=5)}',
        "",
        "# --- OpenClaw ---",
        'OPENCLAW_LOG_DIR="/opt/implant/logs/openclaw"',
        "",
        "# --- WireGuard Keepalive ---",
        f'WG_PING_ATTEMPTS={get(config, "keepalive", "ping_attempts", default=10)}',
        f'WG_SERVER_IP="{get(config, "keepalive", "server_ip", default="10.8.0.1")}"',
        'WG_KEEPALIVE_LOG="/opt/implant/logs/wg-keepalive/wg-keepalive.log"',
    ]

    content = "\n".join(lines) + "\n"
    with open("/opt/implant/config.env", "w") as fh:
        fh.write(content)

    ui.success("config.env generated")
