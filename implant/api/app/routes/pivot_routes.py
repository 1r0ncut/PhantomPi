"""
Pivot route management: add or remove routes through veth1.

POST /pivot-setup  {"subnets": ["192.168.10.0/24", "10.10.5.0/24"]}
POST /pivot-reset  {"subnets": [...]}   # omit or pass [] to reset all
"""

import os
import re
import subprocess

from flask import jsonify, request

VETH_OUT  = "veth1"
SPOOF_LOG = "/opt/implant/logs/spoof-target/spoof-target.log"

_CIDR_RE = re.compile(
    r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$"
)


def _run(cmd):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _veth_ready():
    rc, _, _ = _run(f"ip link show {VETH_OUT} 2>/dev/null")
    return rc == 0


def _get_gateway():
    """Read gateway from the last applied spoof-target log entry."""
    if not os.path.isfile(SPOOF_LOG):
        return None
    try:
        with open(SPOOF_LOG) as fh:
            content = fh.read()
    except OSError:
        return None
    blocks = re.split(r"--- Log Entry:[^\n]*---", content)
    last = next((b.strip() for b in reversed(blocks) if b.strip()), "")
    for line in last.splitlines():
        if line.strip().startswith("Detected Gateway:"):
            val = line.split(":", 1)[1].strip()
            if val and val != "Not set":
                return val
    return None


def _existing_routes():
    rc, out, _ = _run(f"ip route show dev {VETH_OUT} 2>/dev/null")
    subnets = set()
    if rc == 0:
        for line in out.splitlines():
            parts = line.split()
            if parts:
                subnets.add(parts[0])
    return subnets


def register(app):

    @app.route("/pivot-setup", methods=["POST"])
    def pivot_setup():
        if not _veth_ready():
            return jsonify({"error": "pivot not ready: veth1 does not exist"}), 409

        body = request.get_json(silent=True) or {}
        subnets = [s for s in body.get("subnets", []) if _CIDR_RE.match(s)]
        if not subnets:
            return jsonify({"error": "no valid subnets provided"}), 400

        gateway = _get_gateway()
        if not gateway:
            return jsonify({
                "error": "gateway not found in spoof-target log; run spoof-target.sh with --gateway first"
            }), 409

        existing = _existing_routes()
        configured, skipped, failed = [], [], []

        for subnet in subnets:
            if subnet in existing:
                skipped.append(subnet)
                continue
            rc, _, err = _run(
                f"ip route add {subnet} via {gateway} dev {VETH_OUT}"
            )
            if rc == 0:
                configured.append(subnet)
            else:
                failed.append({"subnet": subnet, "error": err})

        return jsonify({
            "gateway":    gateway,
            "configured": configured,
            "skipped":    skipped,
            "failed":     failed,
        })

    @app.route("/pivot-reset", methods=["POST"])
    def pivot_reset():
        body = request.get_json(silent=True) or {}
        subnets = [s for s in body.get("subnets", []) if _CIDR_RE.match(s)]

        removed, failed = [], []

        if not subnets:
            # Flush all routes on veth1
            rc, _, err = _run(f"ip route flush dev {VETH_OUT} 2>/dev/null")
            if rc == 0:
                return jsonify({"removed": "all", "failed": []})
            return jsonify({"removed": [], "failed": [{"subnet": "all", "error": err}]})

        for subnet in subnets:
            rc, _, err = _run(f"ip route del {subnet} 2>/dev/null")
            if rc == 0:
                removed.append(subnet)
            else:
                failed.append({"subnet": subnet, "error": err})

        return jsonify({"removed": removed, "failed": failed})
