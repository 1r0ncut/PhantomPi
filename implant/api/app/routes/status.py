from flask import jsonify
import subprocess


def run_cmd(cmd):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def register(app):
    @app.route("/status", methods=["GET"])
    def status():
        result = {}

        # Interfaces: parse ip -brief address into structured list
        ifaces = []
        for line in run_cmd("ip -brief address").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                ifaces.append({
                    "name":      parts[0],
                    "state":     parts[1],
                    "addresses": parts[2:] if len(parts) > 2 else [],
                })
        result["interfaces"] = ifaces

        # Routes: one entry per line
        result["routes"] = [
            l for l in run_cmd("ip route").splitlines() if l.strip()
        ]

        # Uptime
        result["uptime"] = run_cmd("uptime -p")

        # Listening ports: one entry per line
        result["ports"] = [
            l for l in run_cmd("ss -tuln | grep -i listen").splitlines()
            if l.strip()
        ]

        # Services: structured list, no emojis
        services = [
            "wg-keepalive.timer",
            "bridge-sync.timer",
            "packet-sniffer.service",
            "cred-analyzer.timer",
            "power-monitor.timer",
            "hidden-hotspot.service",
        ]
        result["services"] = [
            {"name": s, "active": run_cmd(f"systemctl is-active {s}") == "active"}
            for s in services
        ]

        return jsonify(result)
