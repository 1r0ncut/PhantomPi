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

import hashlib
import json
import os
import shutil
import stat
from collections import Counter
from datetime import datetime, timezone

from .config import get, get_implant_ip
from .ui import UI


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Log sub-directories under /opt/implant/logs/
_LOG_DIRS = [
    "bridge-sync",
    "hidden-hotspot",
    "traffic-analyzer",
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
    "traffic-analyzer.py",
]

# Symlinks in /usr/local/bin/ for quick operator access
_HELPER_LINKS = {
    "hidden-hotspot": "/opt/implant/scripts/hidden-hotspot.sh",
    "modem-config":   "/opt/implant/scripts/modem-config.sh",
    "spoof-target":   "/opt/implant/scripts/spoof-target.sh",
}

# Files left behind by the pre-traffic-analyzer credential pipeline.
_LEGACY_CRED_ANALYZER_PATHS = [
    "/opt/implant/scripts/cred-analyzer.py",
    "/opt/implant/services/cred-analyzer.service",
    "/opt/implant/timers/cred-analyzer.timer",
    "/opt/implant/logs/cred-analyzer",
    "/etc/logrotate.d/cred-analyzer",
]

_LEGACY_FINDINGS_FILE = "/opt/implant/logs/cred-analyzer/findings.json"
_TRAFFIC_FINDINGS_FILE = "/opt/implant/logs/traffic-analyzer/findings.json"
_TRAFFIC_STATE_FILE = "/opt/implant/logs/traffic-analyzer/state.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def deploy_files(repo_dir: str, ui: UI) -> None:
    """
    Copy implant runtime files from the cloned repository into
    ``/opt/implant/``.  Existing files are overwritten; files already on
    disk that are *not* in the repo (e.g. logs, certs) are preserved.

    The repo layout has runtime directories (api/, scripts/, services/,
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

    # Removed repository files survive copytree upgrades, so migrate any
    # unique findings and clean the analyzer that traffic-analyzer replaced.
    ui.info("Cleaning legacy cred-analyzer deployment ...")
    ui.run(
        "systemctl stop cred-analyzer.timer cred-analyzer.service "
        "2>/dev/null || true",
        check=False,
    )
    ui.run(
        "systemctl disable cred-analyzer.timer cred-analyzer.service "
        "2>/dev/null || true",
        check=False,
    )
    ui.run(
        "systemctl unlink cred-analyzer.timer cred-analyzer.service "
        "2>/dev/null || true",
        check=False,
    )
    migration_ok = _migrate_legacy_findings(ui)
    for path in _LEGACY_CRED_ANALYZER_PATHS:
        if path == "/opt/implant/logs/cred-analyzer" and not migration_ok:
            continue
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path) or os.path.islink(path):
            os.remove(path)
    ui.success("Legacy cred-analyzer deployment removed")


def _load_findings(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, "r") as fh:
        data = json.load(fh)
    findings = data.get("findings", []) if isinstance(data, dict) else data
    if not isinstance(findings, list):
        raise TypeError(f"Invalid findings format in {path}")
    return findings


def _finding_hash(finding: dict) -> str:
    if finding.get("hash"):
        return finding["hash"]
    key = (
        f"{finding.get('type', '')}|{finding.get('protocol', '')}|"
        f"{finding.get('username', '')}|{finding.get('secret', '')}|"
        f"{finding.get('url', '')}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _migrate_legacy_findings(ui: UI) -> bool:
    """Merge unique cred-analyzer findings into traffic-analyzer before cleanup."""
    if not os.path.isfile(_LEGACY_FINDINGS_FILE):
        return True

    try:
        legacy = _load_findings(_LEGACY_FINDINGS_FILE)
        current = _load_findings(_TRAFFIC_FINDINGS_FILE)

        seen = {_finding_hash(finding) for finding in current}
        migrated = 0
        for raw_finding in legacy:
            finding = dict(raw_finding)
            finding_hash = _finding_hash(finding)
            if finding_hash in seen:
                continue
            finding["hash"] = finding_hash
            current.append(finding)
            seen.add(finding_hash)
            migrated += 1

        os.makedirs(os.path.dirname(_TRAFFIC_FINDINGS_FILE), exist_ok=True)
        doc = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_count": len(current),
            "by_type": dict(Counter(f.get("type", "unknown") for f in current)),
            "by_protocol": dict(Counter(f.get("protocol", "unknown") for f in current)),
            "findings": current,
        }
        findings_tmp = _TRAFFIC_FINDINGS_FILE + ".tmp"
        with open(findings_tmp, "w") as fh:
            json.dump(doc, fh, indent=2)
        os.replace(findings_tmp, _TRAFFIC_FINDINGS_FILE)

        state = {"files": {}, "seen": []}
        if os.path.isfile(_TRAFFIC_STATE_FILE):
            try:
                with open(_TRAFFIC_STATE_FILE, "r") as fh:
                    loaded_state = json.load(fh)
                if isinstance(loaded_state, dict):
                    state = loaded_state
            except (json.JSONDecodeError, OSError):
                pass
        state["seen"] = list(set(state.get("seen", [])) | seen)
        state_tmp = _TRAFFIC_STATE_FILE + ".tmp"
        with open(state_tmp, "w") as fh:
            json.dump(state, fh)
        os.replace(state_tmp, _TRAFFIC_STATE_FILE)

        ui.success(f"Migrated {migrated} unique legacy credential findings")
        return True
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        ui.warning(f"Could not migrate legacy credential findings: {exc}")
        ui.warning("Preserving /opt/implant/logs/cred-analyzer for manual recovery")
        return False


def create_log_dirs(ui: UI) -> None:
    """Create every log directory the implant services expect."""
    ui.info("Creating log directories ...")
    for name in _LOG_DIRS:
        os.makedirs(f"/opt/implant/logs/{name}", exist_ok=True)
    # API server log
    os.makedirs("/opt/implant/api/logs", exist_ok=True)
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
        "# --- Traffic Analyzer ---",
        'TRAFFIC_ANALYZER_LOG_DIR="/opt/implant/logs/traffic-analyzer"',
        "",
        "# --- OpenClaw Notifications ---",
        f'OPENCLAW_NOTIFY_BRIDGE="{get(config, "openclaw", "notify_bridge", default="yes")}"',
        f'OPENCLAW_NOTIFY_CREDS="{get(config, "openclaw", "notify_creds", default="yes")}"',
        f'OPENCLAW_REDACT_SECRETS="{get(config, "openclaw", "redact_secrets", default="yes")}"',
        f'OPENCLAW_WEBHOOK_URL="{get(config, "openclaw", "webhook_url", default="")}"',
        f'OPENCLAW_WEBHOOK_TOKEN="{get(config, "openclaw", "webhook_token", default="")}"',
        f'OPENCLAW_ALERT_CHANNEL_ID="{get(config, "openclaw", "alert_channel_id", default="")}"',
        "",
        "# --- WireGuard Keepalive ---",
        f'WG_PING_ATTEMPTS={get(config, "keepalive", "ping_attempts", default=10)}',
        f'WG_SERVER_IP="{get(config, "keepalive", "server_ip", default="10.8.0.1")}"',
        f'WG_MODEM_REBOOT_ATTEMPTS={get(config, "keepalive", "modem_reboot_attempts", default=1)}',
        f'WG_MODEM_REBOOT_WAIT_SECONDS={get(config, "keepalive", "modem_reboot_wait_seconds", default=60)}',
        f'LTE_SERIAL_DEVICE="{get(config, "lte", "serial_device", default="/dev/ttyUSB2")}"',
        'WG_KEEPALIVE_LOG="/opt/implant/logs/wg-keepalive/wg-keepalive.log"',
    ]

    content = "\n".join(lines) + "\n"
    with open("/opt/implant/config.env", "w") as fh:
        fh.write(content)

    ui.success("config.env generated")
