from flask import jsonify
import subprocess

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "<error>"

def register(app):
    @app.route("/status", methods=["GET"])
    def status():
        result = {}

        # 1. Interfaces with IP and MAC
        result['interfaces'] = run_cmd("ip -brief address")

        # 2. Routes
        result['routes'] = run_cmd("ip route")

        # 3. Uptime
        result['uptime'] = run_cmd("uptime -p")

        # 4. Listening Ports
        result['ports'] = run_cmd("ss -tuln | grep -i listen")

        # 5. Custom services (define which ones matter)
        services = ["wg-keepalive.timer", "hidden-hotspot.service", "ntpsec-watchdog.timer", "bridge-sync.timer", "bruteshark.service", "packet-sniffer.service", "power-monitor.timer"]
        status_lines = []
        for s in services:
            state = run_cmd(f"systemctl is-active {s}")
            if state != "active": state = "inactive"
            emoji = "🟢" if state == "active" else "🔴"
            status_lines.append(f"{emoji} `{s}`: {state}")
        result['services'] = "\n".join(status_lines)

        return jsonify(result)
