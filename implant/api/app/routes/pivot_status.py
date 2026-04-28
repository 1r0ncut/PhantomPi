"""
Pivot status endpoint — returns pivot readiness, spoofed identity from the
spoof-target log, current routes on veth1, and internal subnet suggestions
derived from captured traffic PCAPs.
"""

import os
import re
import subprocess
from collections import defaultdict

from flask import jsonify

VETH_IN  = "veth0"
VETH_OUT = "veth1"
SPOOF_LOG = "/opt/implant/logs/spoof-target/spoof-target.log"
PCAP_DIR  = "/opt/implant/logs/packet-sniffer"
PCAP_LIMIT = 5       # most recent PCAP files to analyse
PACKET_CAP = 50000   # max packets read per PCAP (keeps response fast)

# RFC 1918 ranges as (base, mask) integer pairs
_RFC1918 = [
    (0x0A000000, 0xFF000000),  # 10.0.0.0/8
    (0xAC100000, 0xFFF00000),  # 172.16.0.0/12
    (0xC0A80000, 0xFFFF0000),  # 192.168.0.0/16
]



def _run(cmd):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _iface_exists(name):
    return _run(f"ip link show {name} 2>/dev/null") != ""


def _ip_to_int(ip):
    try:
        p = [int(x) for x in ip.split(".")]
        return (p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]
    except Exception:
        return None


def _is_rfc1918(ip):
    n = _ip_to_int(ip)
    if n is None:
        return False
    return any((n & mask) == base for base, mask in _RFC1918)


def _to_slash24(ip):
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


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
    """Analyse recent PCAPs and return ranked list of internal subnets."""
    if not os.path.isdir(PCAP_DIR):
        return []

    try:
        all_files = [
            os.path.join(PCAP_DIR, f)
            for f in os.listdir(PCAP_DIR)
            if f.endswith(".pcap")
        ]
        pcaps = sorted(all_files, key=os.path.getmtime, reverse=True)[:PCAP_LIMIT]
    except OSError:
        return []

    if not pcaps:
        return []

    subnet_data = defaultdict(lambda: {"packets": 0, "protocols": set()})

    for pcap in pcaps:
        out = _run(
            f"tshark -r {pcap} -c {PACKET_CAP} -T fields "
            f"-e ip.dst -e _ws.col.Protocol "
            f"-Y 'ip and not ip.dst == 255.255.255.255' 2>/dev/null"
        )
        for line in out.splitlines():
            parts = line.split("\t")
            dst_ip = parts[0].strip() if parts else ""
            if not dst_ip or not _is_rfc1918(dst_ip):
                continue
            subnet = _to_slash24(dst_ip)
            if not subnet:
                continue
            subnet_data[subnet]["packets"] += 1
            if len(parts) > 1:
                proto = parts[1].strip()
                if proto:
                    subnet_data[subnet]["protocols"].add(proto)

    suggestions = []
    for subnet, data in sorted(
        subnet_data.items(), key=lambda x: x[1]["packets"], reverse=True
    ):
        hints = sorted(data["protocols"])
        suggestions.append({
            "subnet":  subnet,
            "packets": data["packets"],
            "hint":    ", ".join(hints) if hints else "unknown",
        })

    return suggestions


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
