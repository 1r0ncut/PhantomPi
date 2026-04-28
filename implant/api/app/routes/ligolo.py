"""
Ligolo-ng agent session management via tmux.

GET  /ligolo-sessions              list active ligolo-* tmux sessions
POST /ligolo-start  {"proxy_ip": "10.8.0.2", "proxy_port": 11601}
POST /ligolo-kill   {"session": "ligolo-10.8.0.2"} | {"session": "all"}
"""

import re
import subprocess

from flask import jsonify, request

LIGOLO_BINARY  = "/usr/bin/ligolo-agent"
SESSION_PREFIX = "ligolo-"
DEFAULT_PORT   = 11601

_IP_RE      = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_SESSION_RE = re.compile(r"^ligolo-[\d.]+$")


def _run(cmd):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _list_sessions():
    rc, out, _ = _run(
        f"tmux list-sessions -F '#{{session_name}}' 2>/dev/null"
        f" | grep '^{SESSION_PREFIX}'"
    )
    if rc != 0 or not out.strip():
        return []

    sessions = []
    for name in out.splitlines():
        name = name.strip()
        if not name:
            continue
        proxy_ip = name[len(SESSION_PREFIX):]
        # Check whether the pane process is still alive
        rc2, panes, _ = _run(
            f"tmux list-panes -t '{name}' -F '#{{pane_pid}}' 2>/dev/null"
        )
        running = rc2 == 0 and bool(panes.strip())
        sessions.append({
            "session":  name,
            "proxy_ip": proxy_ip,
            "running":  running,
        })
    return sessions


def register(app):

    @app.route("/ligolo-sessions", methods=["GET"])
    def ligolo_sessions():
        return jsonify({"sessions": _list_sessions()})

    @app.route("/ligolo-start", methods=["POST"])
    def ligolo_start():
        body = request.get_json(silent=True) or {}
        proxy_ip   = body.get("proxy_ip", "").strip()
        proxy_port = int(body.get("proxy_port", DEFAULT_PORT))

        if not proxy_ip or not _IP_RE.match(proxy_ip):
            return jsonify({"error": "proxy_ip must be a valid IPv4 address"}), 400

        # Verify binary
        rc, _, _ = _run(f"test -x '{LIGOLO_BINARY}'")
        if rc != 0:
            return jsonify({
                "error": f"ligolo-agent not found or not executable at {LIGOLO_BINARY}"
            }), 500

        session_name = f"{SESSION_PREFIX}{proxy_ip}"

        # Reuse existing session if already up
        rc, _, _ = _run(f"tmux has-session -t '{session_name}' 2>/dev/null")
        if rc == 0:
            return jsonify({
                "session":    session_name,
                "status":     "already_running",
                "proxy_ip":   proxy_ip,
                "proxy_port": proxy_port,
            })

        cmd = (
            f"tmux new-session -d -s '{session_name}' "
            f"'{LIGOLO_BINARY} -connect {proxy_ip}:{proxy_port} -ignore-cert'"
        )
        rc, _, err = _run(cmd)
        if rc != 0:
            return jsonify({"error": f"failed to start tmux session: {err}"}), 500

        return jsonify({
            "session":    session_name,
            "status":     "started",
            "proxy_ip":   proxy_ip,
            "proxy_port": proxy_port,
        })

    @app.route("/ligolo-kill", methods=["POST"])
    def ligolo_kill():
        body = request.get_json(silent=True) or {}
        target = body.get("session", "").strip()

        if not target:
            return jsonify({"error": "'session' is required ('all' or a session name)"}), 400

        killed, failed = [], []

        if target == "all":
            targets = [s["session"] for s in _list_sessions()]
        elif _SESSION_RE.match(target):
            targets = [target]
        else:
            return jsonify({"error": f"invalid session name: {target}"}), 400

        for name in targets:
            rc, _, err = _run(f"tmux kill-session -t '{name}' 2>/dev/null")
            if rc == 0:
                killed.append(name)
            else:
                failed.append({"session": name, "error": err})

        return jsonify({"killed": killed, "failed": failed})
