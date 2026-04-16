"""
PhantomPi Setup — Service & Tool Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Discord Flask API server  (venv, TLS certs, corrected systemd unit)
* BruteShark credential extractor  (.NET 3.1, clone, compile)
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
    "bridge-sync.service":       "/opt/implant/services/bridge-sync.service",
    "bruteshark.service":        "/opt/implant/services/bruteshark.service",
    "discord.service":           "/opt/implant/services/discord.service",
    "hidden-hotspot.service":    "/opt/implant/services/hidden-hotspot.service",
    "packet-sniffer.service":    "/opt/implant/services/packet-sniffer.service",
    "power-monitor.service":     "/opt/implant/services/power-monitor.service",
    "wg-keepalive.service":      "/opt/implant/services/wg-keepalive.service",
    # timers
    "bridge-sync.timer":         "/opt/implant/timers/bridge-sync.timer",
    "power-monitor.timer":       "/opt/implant/timers/power-monitor.timer",
    "wg-keepalive.timer":        "/opt/implant/timers/wg-keepalive.timer",
}

# Timers to ALWAYS enable at boot (safe regardless of config)
_ENABLE_TIMERS_ALWAYS = [
    "bridge-sync.timer",
    "power-monitor.timer",
]

# Timer that must ONLY be enabled when WireGuard is fully configured,
# otherwise the keepalive script will fail to ping the VPN server and
# trigger an infinite reboot loop.
_WG_KEEPALIVE_TIMER = "wg-keepalive.timer"

# Services to ALWAYS enable at boot
_ENABLE_SERVICES = [
    "discord.service",
    "packet-sniffer.service",
]

# Logrotate entries  (name -> log path)
_LOGROTATE: dict[str, str] = {
    "bridge-sync":   "/opt/implant/logs/bridge-sync/bridge-sync.log",
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
# Discord Flask API server
# ---------------------------------------------------------------------------

def setup_discord_api(config: dict, ui: UI, skipped: list) -> None:
    """
    Prepare the implant-side Flask HTTPS server used by the Discord bot:
    * Create a Python virtual-env and install requirements
    * Generate a self-signed TLS certificate (10-year validity)
    * Re-write discord.service so it reads ``IMPLANT_WG_IP`` from
      ``config.env`` via ``EnvironmentFile=``
    """
    discord_dir = "/opt/implant/discord"
    venv_dir    = os.path.join(discord_dir, "venv")
    certs_dir   = os.path.join(discord_dir, "certs")

    # ── virtual-env ───────────────────────────────────────────────────────
    if not os.path.isdir(venv_dir):
        ui.info("Creating Discord API virtual environment ...")
        ui.run(f"python3 -m venv {venv_dir}", timeout=60)
        ui.run(f"{venv_dir}/bin/pip install --upgrade pip -q", timeout=60)
        ui.run(
            f"{venv_dir}/bin/pip install -r {discord_dir}/requirements.txt -q",
            timeout=60,
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

    # ── Rewrite discord.service with EnvironmentFile ──────────────────────
    ui.info("Updating discord.service with dynamic WireGuard IP binding ...")
    svc = (
        "[Unit]\n"
        "Description=Implant Flask HTTPS Server for Discord Bot\n"
        "After=network-online.target wg-quick@wg0.service\n"
        "Wants=network-online.target wg-quick@wg0.service\n"
        "\n"
        "[Service]\n"
        "WorkingDirectory=/opt/implant/discord\n"
        "EnvironmentFile=/opt/implant/config.env\n"
        "ExecStart=/opt/implant/discord/venv/bin/gunicorn \\\n"
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
    with open("/opt/implant/services/discord.service", "w") as fh:
        fh.write(svc)
    ui.success("discord.service updated")


# ---------------------------------------------------------------------------
# BruteShark credential extractor
# ---------------------------------------------------------------------------

def setup_bruteshark(ui: UI, *, skip: bool = False) -> bool:
    """
    Install the .NET Core 3.1 SDK, clone BruteShark, and compile
    ``BruteSharkCli``.  Returns True on success.

    The build is entirely optional — pass ``skip=True`` (via
    ``--skip-bruteshark``) to bypass it.
    """
    if skip:
        ui.skipped("BruteShark installation skipped (--skip-bruteshark)")
        return False

    bs_bin = "/usr/local/bin/BruteSharkCli"
    if os.path.isfile(bs_bin):
        ui.success("BruteShark already installed")
        return True

    try:
        # ── .NET Core 3.1 SDK ─────────────────────────────────────────────
        dotnet_check = ui.run(
            "DOTNET_ROOT=/root/.dotnet PATH=$PATH:/root/.dotnet "
            "dotnet --list-sdks 2>/dev/null | grep -q '^3\\.'",
            check=False,
        )
        if dotnet_check.returncode == 0:
            ui.success(".NET Core 3.1 SDK already installed")
        else:
            ui.info("Installing .NET Core 3.1 SDK (may take several minutes) ...")
            ui.run(
                "curl -sSL https://dot.net/v1/dotnet-install.sh "
                "| bash /dev/stdin --channel 3.1",
                timeout=300,
            )

            # Fix native-lib symlink required by the runtime
            ui.run(
                "ln -sf /lib/aarch64-linux-gnu/libdl.so.2 "
                "/lib/aarch64-linux-gnu/libdl.so 2>/dev/null || true",
                check=False,
            )

        # libssl1.1 compatibility package (needed by .NET 3.1 on newer Kali)
        # Checked on EVERY run — the SDK install may have succeeded on a
        # previous run while libssl was missing or later removed.
        libssl_check = ui.run(
            "ldconfig -p 2>/dev/null | grep -q 'libssl.so.1.1'",
            check=False,
        )
        if libssl_check.returncode == 0:
            ui.success("libssl1.1 already available")
        else:
            # The exact filename changes with security updates, so we
            # scrape the Debian pool directory for the latest arm64 deb.
            ui.info("Installing libssl1.1 compatibility ...")
            ui.run(
                "cd /tmp && "
                "POOL='http://security.debian.org/debian-security/pool/"
                "updates/main/o/openssl' && "
                "DEB=$(curl -sL \"$POOL/\" "
                "| grep -oP 'libssl1\\.1_[^\"]+_arm64\\.deb' "
                "| sort -V | tail -1) && "
                "[ -n \"$DEB\" ] && "
                "wget -q \"$POOL/$DEB\" && "
                "dpkg -i \"$DEB\"",
                timeout=120, check=False,
            )

        # Persist environment for future shells
        _ensure_dotnet_env()

        # Shell snippet to set env for the current build commands
        dotnet_env = (
            "export DOTNET_ROOT=/root/.dotnet && "
            "export PATH=$PATH:/root/.dotnet && "
            "export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1"
        )

        # ── Clone & compile ───────────────────────────────────────────────
        bs_src = "/opt/implant/scripts/BruteShark/src"
        if not os.path.isdir(bs_src):
            ui.info("Cloning BruteShark repository ...")
            ui.run(
                f"git clone --depth 1 "
                f"https://github.com/odedshimon/BruteShark.git {bs_src}",
                timeout=120,
            )

        cli_proj = os.path.join(bs_src, "BruteShark", "BruteSharkCli")
        cli_bin  = os.path.join(
            cli_proj, "bin", "Release", "netcoreapp3.1", "BruteSharkCli"
        )

        # ── Compile (skip if binary already built) ────────────────────────
        if os.path.isfile(cli_bin):
            ui.success("BruteSharkCli already compiled")
        else:
            ui.info("Compiling BruteSharkCli (may take several minutes) ...")
            ui.run(
                f"{dotnet_env} && cd {cli_proj} && "
                f"dotnet build --configuration Release",
                timeout=600,
            )

        # ── Symlink the binary ────────────────────────────────────────────
        if os.path.isfile(cli_bin):
            if os.path.islink(bs_bin):
                os.unlink(bs_bin)
            os.symlink(cli_bin, bs_bin)
            ui.success("BruteShark linked to /usr/local/bin/")
            return True

        ui.warning("BruteSharkCli binary not found after compilation")
        return False

    except Exception as exc:
        ui.warning(f"BruteShark installation failed: {exc}")
        ui.warning("Install manually later — see the project wiki for steps")
        return False


# ---------------------------------------------------------------------------
# systemd units
# ---------------------------------------------------------------------------

def configure_systemd(ui: UI, *, wg_configured: bool = False) -> None:
    """
    Create symlinks in ``/etc/systemd/system/`` for every implant
    service and timer, then enable the ones that should start at boot.

    Parameters
    ----------
    wg_configured : bool
        When True the WireGuard tunnel is fully configured and
        ``wg-keepalive.timer`` is safe to enable.  When False the timer
        is left *disabled* to avoid a reboot loop (the keepalive script
        reboots the device when it cannot reach the VPN server).
    """
    ui.info("Creating systemd unit symlinks ...")

    for unit_name, source in _SYSTEMD_UNITS.items():
        link = f"/etc/systemd/system/{unit_name}"
        # Remove stale link (or regular file) before (re)creating
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        if os.path.isfile(source):
            os.symlink(source, link)
            ui.debug(f"  {unit_name} -> {source}")
        else:
            ui.debug(f"  {unit_name}: source not found ({source})")

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
    ui.success("Systemd units linked and daemon reloaded")

    # Enable timers — always-safe ones first
    ui.info("Enabling boot-time timers and services ...")
    for timer in _ENABLE_TIMERS_ALWAYS:
        ui.run(f"systemctl enable {timer} 2>/dev/null || true", check=False)

    # wg-keepalive only when the VPN is ready (prevents reboot loop)
    if wg_configured:
        ui.run(
            f"systemctl enable {_WG_KEEPALIVE_TIMER} 2>/dev/null || true",
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
        ui.run(f"systemctl enable {svc} 2>/dev/null || true", check=False)
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
            f"sed -e 's#/home/pi/wittypi#{wittypi_dir}#g' "
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
                f"sed -e 's#/home/pi/uwi#{uwi_dir}#g' "
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

    # ── Set default-ON power state ────────────────────────────────────
    # I2C register 17 (I2C_CONF_DEFAULT_ON) on bus 1, address 0x08:
    #   0x00 = Default OFF (button press required to power on)
    #   0x01 = Default ON  (auto-power when supply is connected)
    # Uses Witty Pi's own i2c_write (write + verify + retry up to 4x)
    # instead of raw i2cset which silently fails if the MCU is busy.
    ui.info("Setting Witty Pi to 'Default ON' (auto-power) ...")
    ui.run(
        "cd /opt/implant/wittypi/wittypi && source utilities.sh && i2c_write 0x01 $I2C_MC_ADDRESS $I2C_CONF_DEFAULT_ON 0x01",
        check=False,
    )
    ui.success("Witty Pi set to Default ON (register 17 = 0x01)")

    # ── Verify ────────────────────────────────────────────────────────
    if os.path.isfile("/etc/init.d/wittypi"):
        ui.success("Witty Pi 4 installed and daemon registered")
        return True

    ui.warning("Witty Pi daemon registration failed")
    return False


def _ensure_dotnet_env() -> None:
    """Append .NET environment variables to ``/root/.bashrc`` if missing."""
    bashrc = "/root/.bashrc"
    if not os.path.isfile(bashrc):
        return
    with open(bashrc, "r") as fh:
        content = fh.read()

    additions: list[str] = []
    if "DOTNET_ROOT" not in content:
        additions.append("export DOTNET_ROOT=/root/.dotnet")
    if "/root/.dotnet" not in content:
        additions.append("export PATH=$PATH:/root/.dotnet")
    if "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT" not in content:
        additions.append("export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1")

    if additions:
        with open(bashrc, "a") as fh:
            fh.write("\n# PhantomPi — .NET SDK environment\n")
            fh.write("\n".join(additions) + "\n")
