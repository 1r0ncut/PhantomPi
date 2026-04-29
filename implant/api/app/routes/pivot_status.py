"""
Pivot status endpoint: returns pivot readiness, spoofed identity from the
spoof-target log, current routes on veth1, and suggested subnets from the
traffic-analyzer pre-computed cache (subnet-suggestions.json).
"""

import json
import os
import re
import subprocess

from flask import jsonify

VETH_IN      = "veth0"
VETH_OUT     = "veth1"
SPOOF_LOG    = "/opt/implant/logs/spoof-target/spoof-target.log"
SUBNETS_FILE = "/opt/implant/logs/traffic-analyzer/subnet-suggestions.json"


def _run(cmd):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _iface_exists(name):
    return _run(f"ip link show {name} 2>/dev/null") != ""


def _parse_spoof_log():
    """Return the last successfully applied entry from spoof-target.log."""
    if not os.path.isfile(SPOOF_LOG):
        return {}
    try:
        with open(SPOOF_LOG) as fh:
            content = fh.read()
    except OSError:
        return {}

    # Split on entry headers; take last non-empty block
    blocks = re.split(r"--- Log Entry:[^\n]*---", content)
    last = next((b.strip() for b in reversed(blocks) if b.strip()), "")
    if not last:
        return {}

    # Only return entries where settings were actually applied
    if "Settings applied successfully" not in last:
        return {}

    mapping = {
        "Spoofed IP":       "ip",
        "Spoofed MAC":      "mac",
        "Spoofed Hostname": "hostname",
        "Detected Gateway": "gateway",
        "Detected DNS":     "dns",
    }
    result = {}
    for line in last.splitlines():
        for label, key in mapping.items():
            if line.strip().startswith(f"{label}:"):
                val = line.split(":", 1)[1].strip()
                if val and val != "Not set":
                    result[key] = val
    return result


def _current_routes():
    out = _run(f"ip route show dev {VETH_OUT} 2>/dev/null")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _suggest_subnets():
    """
    Read pre-computed subnet suggestions written by traffic-analyzer.
    Returns instantly -- no PCAP processing at query time.
    """
    if not os.path.isfile(SUBNETS_FILE):
        return []
    try:
        with open(SUBNETS_FILE) as fh:
            data = json.load(fh)
        return data.get("suggestions", [])
    except (json.JSONDecodeError, OSError):
        return []


def register(app):
    @app.route("/pivot-status", methods=["GET"])
    def pivot_status():
        pivot_ready = _iface_exists(VETH_IN) and _iface_exists(VETH_OUT)
        return jsonify({
            "pivot_ready":       pivot_ready,
            "spoofed":           _parse_spoof_log(),
            "current_routes":    _current_routes(),
            "suggested_subnets": _suggest_subnets() if pivot_ready else [],
        })
