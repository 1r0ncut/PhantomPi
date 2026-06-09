"""
PhantomPi Setup — Service & Tool Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Flask HTTPS API server  (venv, TLS certs, corrected systemd unit)
* systemd unit symlinks + timer/service enablement
* Logrotate rules for every implant log
* Hidden-hotspot NetworkManager profile creation
"""

from __future__ import annotations

import os

from .config import get, get_implant_ip
from .ui import UI



# ---------------------------------------------------------------------------
# systemd unit mapping   name -> source path under /opt/implant/
# ---------------------------------------------------------------------------
_SYSTEMD_UNITS: dict[str, str] = {
    # services
    "bridge-sync.service":              "/opt/implant/services/bridge-sync.service",
    "implant-api.service":              "/opt/implant/services/implant-api.service",
    "hidden-hotspot.service":           "/opt/implant/services/hidden-hotspot.service",
    "traffic-analyzer.service":         "/opt/implant/services/traffic-analyzer.service",
    "packet-sniffer.service":           "/opt/implant/services/packet-sniffer.service",
    "power-monitor.service":            "/opt/implant/services/power-monitor.service",
    "wg-keepalive.service":             "/opt/implant/services/wg-keepalive.service",
    # timers
    "bridge-sync.timer":                "/opt/implant/timers/bridge-sync.timer",
    "traffic-analyzer.timer":           "/opt/implant/timers/traffic-analyzer.timer",
    "power-monitor.timer":              "/opt/implant/timers/power-monitor.timer",
    "wg-keepalive.timer":               "/opt/implant/timers/wg-keepalive.timer",
}

# Timers to ALWAYS enable at boot (safe regardless of config)
_ENABLE_TIMERS_ALWAYS = [
    "bridge-sync.timer",
    "power-monitor.timer",
]

# Timers controlled by bridge-sync rather than enabled at boot.
_BRIDGE_MANAGED_TIMERS = [
    "traffic-analyzer.timer",
]

# Timer that must ONLY be enabled when WireGuard is fully configured,
# otherwise the keepalive script will fail to ping the VPN server and
# trigger an infinite reboot loop.
_WG_KEEPALIVE_TIMER = "wg-keepalive.timer"

# Services to ALWAYS enable at boot
_ENABLE_SERVICES = [
    "implant-api.service",
    "packet-sniffer.service",
]

# Logrotate entries  (name -> log path)
_LOGROTATE: dict[str, str] = {
    "bridge-sync":   "/opt/implant/logs/bridge-sync/bridge-sync.log",
    "traffic-analyzer": "/opt/implant/logs/traffic-analyzer/traffic-analyzer.log",
    "wg-keepalive":  "/opt/implant/logs/wg-keepalive/wg-keepalive.log",
    "power-monitor": "/opt/implant/logs/power-monitor/power-monitor.log",
}

_LOGROTATE_TEMPLATE = """\
{path} {{
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 root root
    copytruncate
}}
"""


# ---------------------------------------------------------------------------
# Flask HTTPS API server
# ---------------------------------------------------------------------------

def setup_api_server(config: dict, ui: UI, skipped: list) -> None:
    """
    Prepare the implant-side Flask HTTPS API server:
    * Create a Python virtual-env and install requirements (incl. scapy)
    * Generate a self-signed TLS certificate (10-year validity)
    * Re-write implant-api.service so it reads ``IMPLANT_WG_IP`` from
      ``config.env`` via ``EnvironmentFile=``
    """
    api_dir   = "/opt/implant/api"
    venv_dir  = os.path.join(api_dir, "venv")
    certs_dir = os.path.join(api_dir, "certs")

    # ── virtual-env ───────────────────────────────────────────────────────
    if not os.path.isdir(venv_dir):
        ui.info("Creating API server virtual environment ...")
        ui.run(f"python3 -m venv {venv_dir}", timeout=60)
        ui.run(f"{venv_dir}/bin/pip install --upgrade pip -q", timeout=60)
        ui.run(
            f"{venv_dir}/bin/pip install -r {api_dir}/requirements.txt -q",
            timeout=120,
        )
        ui.success("Virtual environment created")
    else:
        ui.success("Virtual environment already exists")

    # ── TLS certificate ───────────────────────────────────────────────────
    os.makedirs(certs_dir, exist_ok=True)
    cert_pem = os.path.join(certs_dir, "cert.pem")
    key_pem  = os.path.join(certs_dir, "key.pem")

    if not os.path.isfile(cert_pem):
        ui.info("Generating self-signed TLS certificate (10 years) ...")
        ui.run(
            f"openssl req -new -x509 -newkey rsa:2048 "
            f"-keyout {key_pem} -out {cert_pem} "
            f"-days 3650 -nodes -subj '/CN=implant.local'"
        )
        os.chmod(key_pem, 0o600)
        os.chmod(cert_pem, 0o644)
        ui.success("TLS certificate generated")
    else:
        ui.success("TLS certificate already exists")

    # ── Rewrite implant-api.service with EnvironmentFile ──────────────────────
    ui.info("Updating implant-api.service with dynamic WireGuard IP binding ...")
    svc = (
        "[Unit]\n"
        "Description=Implant Flask HTTPS API Server\n"
        "After=network-online.target wg-quick@wg0.service\n"
        "Wants=network-online.target wg-quick@wg0.service\n"
        "\n"
        "[Service]\n"
        "WorkingDirectory=/opt/implant/api\n"
        "EnvironmentFile=/opt/implant/config.env\n"
        "ExecStart=/opt/implant/api/venv/bin/gunicorn \\\n"
        "    --certfile=certs/cert.pem \\\n"
        "    --keyfile=certs/key.pem \\\n"
        "    --bind ${IMPLANT_WG_IP}:8443 \\\n"
        "    wsgi:app\n"
        "Restart=always\n"
        "RestartSec=3\n"
        "User=root\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    with open("/opt/implant/services/implant-api.service", "w") as fh:
        fh.write(svc)
    ui.success("implant-api.service updated")


# ---------------------------------------------------------------------------
# systemd units
# ---------------------------------------------------------------------------

def configure_systemd(ui: UI, *, wg_configured: bool = False) -> None:
    """
    Register and enable implant systemd units.

    * Service units driven by timers are registered with ``systemctl link``
      (makes them known to systemd without enabling them at boot).
    * Timers and standalone services are enabled with
      ``systemctl enable /full/path`` so systemd handles symlink placement
      based on each unit's ``[Install]`` section.

    Parameters
    ----------
    wg_configured : bool
        When True the WireGuard tunnel is fully configured and
        ``wg-keepalive.timer`` is safe to enable.  When False the timer
        is left *disabled* to avoid a reboot loop (the keepalive script
        reboots the device when it cannot reach the VPN server).
    """
    ui.info("Registering systemd units ...")

    # Clear legacy boot enablement before linking units. Disabling a linked
    # unit removes its systemd link, so doing this afterward would make the
    # bridge-managed timer impossible to start.
    for timer in _BRIDGE_MANAGED_TIMERS:
        ui.run(f"systemctl disable --now {timer} 2>/dev/null || true", check=False)
        service = timer.removesuffix(".timer") + ".service"
        ui.run(f"systemctl stop {service} 2>/dev/null || true", check=False)

    for unit_name, source in _SYSTEMD_UNITS.items():
        if not os.path.isfile(source):
            ui.debug(f"  {unit_name}: source not found ({source}), skipping")
            continue
        ui.run(f"systemctl link {source} 2>/dev/null || true", check=False)
        ui.debug(f"  linked {source}")

    # ── Cap NM-wait-online timeout ──────────────────────────────────
    # The default 60 s timeout delays wg-quick@wg0 (which depends on
    # network-online.target).  The modem typically connects in <30 s;
    # a 30 s cap avoids unnecessarily long boots on LTE delays.
    dropin_dir = "/etc/systemd/system/NetworkManager-wait-online.service.d"
    os.makedirs(dropin_dir, exist_ok=True)
    dropin = os.path.join(dropin_dir, "timeout.conf")
    if not os.path.isfile(dropin):
        with open(dropin, "w") as fh:
            fh.write(
                "[Service]\n"
                "ExecStart=\n"
                "ExecStart=/usr/bin/nm-online -s -q --timeout=30\n"
            )
        ui.success("NM-wait-online timeout capped at 30 s")

    ui.run("systemctl daemon-reload")
    ui.success("Systemd units registered and daemon reloaded")

    # Enable timers — always-safe ones first (full path so systemd places
    # the symlink based on the unit's own [Install] section)
    ui.info("Enabling boot-time timers and services ...")
    for timer in _ENABLE_TIMERS_ALWAYS:
        source = _SYSTEMD_UNITS.get(timer)
        if source and os.path.isfile(source):
            ui.run(f"systemctl enable {source} 2>/dev/null || true", check=False)

    ui.success("Bridge-managed analyzer timers left disabled at boot")

    # wg-keepalive only when the VPN is ready (prevents reboot loop)
    wg_timer_source = _SYSTEMD_UNITS.get(_WG_KEEPALIVE_TIMER, "")
    if wg_configured:
        if wg_timer_source and os.path.isfile(wg_timer_source):
            ui.run(
                f"systemctl enable {wg_timer_source} 2>/dev/null || true",
                check=False,
            )
        ui.success("wg-keepalive.timer enabled (WireGuard is configured)")
    else:
        ui.run(
            f"systemctl disable {_WG_KEEPALIVE_TIMER} 2>/dev/null || true",
            check=False,
        )
        ui.warning(
            "wg-keepalive.timer left DISABLED — enable it after "
            "configuring WireGuard to avoid a reboot loop"
        )

    for svc in _ENABLE_SERVICES:
        source = _SYSTEMD_UNITS.get(svc)
        if source and os.path.isfile(source):
            ui.run(f"systemctl enable {source} 2>/dev/null || true", check=False)
    ui.success("Timers and services enabled")


# ---------------------------------------------------------------------------
# Logrotate
# ---------------------------------------------------------------------------

def configure_logrotate(ui: UI) -> None:
    """Write logrotate config snippets for all implant log files."""
    ui.info("Configuring log rotation ...")
    for name, path in _LOGROTATE.items():
        conf = _LOGROTATE_TEMPLATE.format(path=path)
        with open(f"/etc/logrotate.d/{name}", "w") as fh:
            fh.write(conf)
    ui.success("Logrotate configured")


# ---------------------------------------------------------------------------
# Hidden hotspot
# ---------------------------------------------------------------------------

def create_hotspot(config: dict, ui: UI, skipped: list) -> None:
    """
    Create a hidden Wi-Fi AP profile via NetworkManager.  Requires a
    PSK of at least 8 characters (WPA2 minimum).
    """
    psk = get(config, "hotspot", "psk", default="")
    if not psk or len(psk) < 8:
        ui.skipped("Hotspot profile NOT created — PSK is empty or < 8 chars")
        skipped.append(
            "Hotspot not created — set hotspot.psk (min 8 chars) in "
            "init.json, then run:  hidden-hotspot create"
        )
        return

    ssid   = get(config, "hotspot", "ssid",      default="berry_ap")
    iface  = get(config, "hotspot", "interface",  default="wlan0")
    hidden = "yes" if get(config, "hotspot", "hidden", default=True) else "no"

    ui.info(f"Creating hidden hotspot profile '{ssid}' ...")

    # Remove a previous profile with the same name (idempotent)
    ui.run(f"nmcli connection delete '{ssid}' 2>/dev/null || true", check=False)

    result = ui.run(
        f"nmcli connection add type wifi ifname {iface} "
        f"con-name '{ssid}' ssid '{ssid}' mode ap autoconnect no "
        f"802-11-wireless.hidden {hidden} "
        f"wifi-sec.key-mgmt wpa-psk wifi-sec.psk '{psk}' "
        f"ipv4.method shared",
        check=False,
    )

    if result.returncode == 0:
        ui.success(f"Hotspot profile '{ssid}' created")
        # Enable the hidden-hotspot service at boot so the AP comes up
        # automatically — useful for emergency local access during install.
        ui.run(
            "systemctl enable hidden-hotspot.service 2>/dev/null || true",
            check=False,
        )
        ui.success("hidden-hotspot.service enabled at boot")
    else:
        ui.warning("Hotspot creation failed — create manually:  hidden-hotspot create")
        skipped.append(
            "Hotspot creation failed — after reboot run:  hidden-hotspot create  "
            "then:  systemctl enable hidden-hotspot.service"
        )


# ---------------------------------------------------------------------------
# Witty Pi 4 power management HAT
# ---------------------------------------------------------------------------

def setup_wittypi(config: dict, ui: UI) -> bool:
    """
    Install the Witty Pi 4 power-management HAT.

    Uses the **official** ``install.sh`` for prerequisites (I2C, wiringPi,
    locale, UWI).  The script's own daemon-registration block is skipped
    when it detects the ``wittypi/`` directory already exists (which it
    does, because our deploy step creates it).  In that case we register
    the daemon ourselves using the vendor's ``init.sh`` template — the
    same ``sed`` command ``install.sh`` uses internally.

    Returns True on success, False if the install script is missing.
    """
    wittypi_dir = "/opt/implant/wittypi"
    install_sh  = os.path.join(wittypi_dir, "install.sh")

    # ── Always: set default-ON power state ───────────────────────────
    # Register 17 (I2C_CONF_DEFAULT_ON) must be written on every setup
    # run — it was previously skipped due to early returns in the daemon
    # registration flow.
    #
    # ui.run() uses subprocess shell=True which invokes /bin/sh (dash on
    # Kali/Debian).  dash does not support the 'source' builtin, so all
    # commands that source utilities.sh must be wrapped in bash -c '...'.
    # reset.sh avoids this because it declares #!/bin/bash at the top.
    #
    # On a truly fresh image the I2C kernel module may not be loaded yet.
    # We load it live (no reboot needed for the module) before the write.
    ui.run(
        "modprobe i2c-bcm2835 2>/dev/null || modprobe i2c-bcm2708 2>/dev/null || true",
        check=False,
    )
    ui.run("modprobe i2c-dev 2>/dev/null || true", check=False)

    utilities_sh = os.path.join(wittypi_dir, "wittypi", "utilities.sh")
    if os.path.isfile(utilities_sh):
        ui.info("Setting Witty Pi to 'Default ON' (auto-power on supply) ...")
        ui.run(
            f"bash -c '(cd {wittypi_dir}/wittypi && source utilities.sh && "
            "i2c_write 0x01 $I2C_MC_ADDRESS $I2C_CONF_DEFAULT_ON 0x01)'",
            check=False,
        )
        ui.success("Witty Pi register 17 = 0x01 (Default ON)")
    else:
        # utilities.sh not deployed yet (very first run before install.sh) —
        # fall back to raw i2cset; the wrapper will be used on re-runs.
        ui.info("Setting Witty Pi default-ON via i2cset (utilities.sh not deployed yet) ...")
        ui.run("i2cset -y 1 0x08 17 0x01 2>/dev/null || true", check=False)
        ui.success("Witty Pi register 17 = 0x01 (Default ON, raw i2cset)")

    # ── Already installed? ────────────────────────────────────────────
    if os.path.isfile("/etc/init.d/wittypi"):
        ui.success("Witty Pi daemon already registered")
        return True

    # ── install.sh present? ───────────────────────────────────────────
    if not os.path.isfile(install_sh):
        ui.warning(
            "Witty Pi install.sh not found at /opt/implant/wittypi/ — "
            "download from https://www.uugear.com/repo/WittyPi4/"
        )
        return False

    # ── Run official install.sh for prerequisites ─────────────────────
    # Handles: I2C enablement, i2c-tools, wiringPi, locale, UWI.
    # The script detects that the wittypi/ directory already exists and
    # prints "Seems wittypi is installed already, skip this step." for
    # the daemon part — that is expected.
    ui.info("Running official Witty Pi install.sh (prerequisites) ...")
    ui.run(
        f"cd {wittypi_dir} && bash install.sh",
        timeout=180,
        check=False,
    )

    # ── Daemon registration ───────────────────────────────────────────
    # If install.sh already did it (e.g. fresh install), we're done.
    if os.path.isfile("/etc/init.d/wittypi"):
        ui.success("Witty Pi 4 installed via official script")
        return True

    # install.sh skipped daemon registration because our directory
    # already exists.  Register using the vendor's init.sh template
    # (same logic as install.sh line 140).
    init_sh = os.path.join(wittypi_dir, "init.sh")
    if os.path.isfile(init_sh):
        ui.info("Registering Witty Pi daemon from vendor init.sh template ...")
        ui.run(
            f"sed -e 's#/home/[^/]*/wittypi#{wittypi_dir}#g' "
            f"'{init_sh}' > /etc/init.d/wittypi && "
            f"chmod +x /etc/init.d/wittypi && "
            f"update-rc.d wittypi defaults",
            check=False,
        )
    else:
        # No vendor template — create a minimal init script
        ui.info("Creating Witty Pi init.d entry (no vendor template found) ...")
        initd = (
            "#!/bin/bash\n"
            "### BEGIN INIT INFO\n"
            "# Provides:          wittypi\n"
            "# Required-Start:    $local_fs\n"
            "# Required-Stop:     $local_fs\n"
            "# Default-Start:     2 3 4 5\n"
            "# Default-Stop:      0 1 6\n"
            "# Short-Description: Witty Pi 4 daemon\n"
            "### END INIT INFO\n"
            "\n"
            f'WITTYPI_DIR="{wittypi_dir}"\n'
            'case "$1" in\n'
            '    start) cd "$WITTYPI_DIR" && bash daemon.sh & ;;\n'
            '    stop)  pkill -f "$WITTYPI_DIR/daemon.sh" 2>/dev/null ;;\n'
            "esac\n"
            "exit 0\n"
        )
        with open("/etc/init.d/wittypi", "w") as fh:
            fh.write(initd)
        os.chmod("/etc/init.d/wittypi", 0o755)
        ui.run("update-rc.d wittypi defaults", check=False)

    # ── Set script permissions ────────────────────────────────────────
    for script in ("daemon.sh", "wittyPi.sh", "runScript.sh",
                   "syncTime.sh", "afterStartup.sh", "beforeScript.sh",
                   "beforeShutdown.sh"):
        path = os.path.join(wittypi_dir, script)
        if os.path.isfile(path):
            os.chmod(path, 0o755)

    # UWI scripts + binary (deploy may not preserve the execute bit)
    for uwi_file in ("uwi.sh", "messanger.sh", "diagnose.sh",
                      "websocketd"):
        path = os.path.join(wittypi_dir, "uwi", uwi_file)
        if os.path.isfile(path):
            os.chmod(path, 0o755)

    # ── Register UWI init.d entry ─────────────────────────────────────
    # The vendor template at uwi/uwi has hardcoded /home/pi/uwi/ paths.
    # Rewrite them to our actual location so the UWI web server starts
    # at boot.  uwi.sh has a built-in retry loop that keeps trying
    # every 5 s until websocketd can bind (handles WG IP timing).
    uwi_dir = os.path.join(wittypi_dir, "uwi")
    uwi_initd_tmpl = os.path.join(uwi_dir, "uwi")
    if not os.path.isfile("/etc/init.d/uwi"):
        if os.path.isfile(uwi_initd_tmpl):
            ui.info("Registering UWI init.d entry ...")
            ui.run(
                f"sed -e 's#/home/[^/]*/uwi#{uwi_dir}#g' "
                f"'{uwi_initd_tmpl}' > /etc/init.d/uwi && "
                f"chmod +x /etc/init.d/uwi && "
                f"update-rc.d uwi defaults",
                check=False,
            )
            ui.success("UWI init.d entry registered")
        else:
            ui.warning("UWI init.d template not found — UWI must be "
                       "started manually")
    else:
        ui.success("UWI init.d entry already registered")

    # ── Ensure WittyPi binaries are executable ──────────────────────
    ui.run(
        f"find {wittypi_dir} -type f \\( -name '*.sh' -o -name 'websocketd' -o -name 'daemon.sh' \\) "
        f"-exec chmod +x {{}} +",
        check=False,
    )

    # ── Configure UWI to bind to WireGuard IP ───────────────────────
    # install.sh runs the UWI installer which may overwrite uwi.conf.
    # Use the same sed command as diagnose.sh's configUWI() to set
    # the WireGuard IP.
    uwi_conf = os.path.join(uwi_dir, "uwi.conf")
    if os.path.isfile(uwi_conf):
        wg_ip = get_implant_ip(config)
        ui.info(f"Configuring UWI to bind to WireGuard IP {wg_ip} ...")
        ui.run(
            f"sed -i \"s_\\(host=\\)\\(.*\\)_\\1'{wg_ip}';_\" '{uwi_conf}'",
            check=False,
        )
        ui.success(f"UWI configured for {wg_ip}:8000")

    # ── Verify ────────────────────────────────────────────────────────
    if os.path.isfile("/etc/init.d/wittypi"):
        ui.success("Witty Pi 4 installed and daemon registered")
        return True

    ui.warning("Witty Pi daemon registration failed")
    return False
