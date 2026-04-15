"""
PhantomPi Setup — Network Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Persistent udev rules for USB interface naming (eth1 / eth2)
* NetworkManager & systemd-networkd "unmanaged" settings for eth0 / eth2
* LTE modem NetworkManager profile (eth1)
* WireGuard key generation and wg0.conf creation
"""

from __future__ import annotations

import fcntl
import os
import select
import shutil
import termios
import time

from .config import get, get_implant_ip
from .ui import UI


# ---------------------------------------------------------------------------
# udev — persistent interface names
# ---------------------------------------------------------------------------

def configure_udev_rules(config: dict, ui: UI) -> None:
    """
    Write udev rules that pin eth1 (LTE modem) and eth2 (USB-to-Ethernet)
    to their physical USB port paths, regardless of probe order.
    """
    lte_path = get(config, "network", "lte_modem_usb_path",     default="1-1.3")
    eth_path = get(config, "network", "usb_eth_adapter_usb_path", default="2-1")

    ui.info("Writing udev rules for persistent interface naming ...")
    rules = (
        "# PhantomPi — bind USB network devices to fixed names\n"
        f'SUBSYSTEM=="net", ACTION=="add", SUBSYSTEMS=="usb", '
        f'DRIVERS=="?*", KERNELS=="{lte_path}", NAME="eth1"\n'
        f'SUBSYSTEM=="net", ACTION=="add", SUBSYSTEMS=="usb", '
        f'DRIVERS=="?*", KERNELS=="{eth_path}", NAME="eth2"\n'
    )
    with open("/etc/udev/rules.d/10-persistent-net.rules", "w") as fh:
        fh.write(rules)

    ui.run("udevadm control --reload 2>/dev/null || true", check=False)
    ui.success("udev rules installed")


# ---------------------------------------------------------------------------
# NetworkManager / systemd-networkd — unmanaged interfaces
# ---------------------------------------------------------------------------

def configure_nm_unmanaged(config: dict, ui: UI) -> None:
    """
    Mark the corporate-side (eth0) and target-side (eth2) interfaces as
    *unmanaged* to prevent unsolicited DHCP or auto-configuration that
    would reveal the implant on the LAN.
    """
    iface_co = get(config, "network", "iface_company", default="eth0")
    iface_tg = get(config, "network", "iface_target",  default="eth2")

    ui.info(f"Marking {iface_co} and {iface_tg} as unmanaged ...")

    # ── NetworkManager drop-in ────────────────────────────────────────────
    os.makedirs("/etc/NetworkManager/conf.d", exist_ok=True)
    with open("/etc/NetworkManager/conf.d/unmanaged.conf", "w") as fh:
        fh.write(
            "# PhantomPi — keep bridge interfaces out of NM\n"
            "[keyfile]\n"
            f"unmanaged-devices="
            f"interface-name:{iface_co};interface-name:{iface_tg}\n"
        )

    # ── Ignore serial/modem devices in NM ─────────────────────────────────
    nm_main = "/etc/NetworkManager/NetworkManager.conf"
    if os.path.isfile(nm_main):
        with open(nm_main, "r") as fh:
            content = fh.read()
        if "ttyUSB" not in content:
            with open(nm_main, "a") as fh:
                fh.write(
                    "\n# PhantomPi — ignore modem serial ports\n"
                    "[keyfile]\n"
                    "unmanaged-devices=interface-name:ttyUSB*\n"
                )

    # ── systemd-networkd drop-ins ─────────────────────────────────────────
    os.makedirs("/etc/systemd/network", exist_ok=True)
    for iface in (iface_co, iface_tg):
        with open(f"/etc/systemd/network/10-{iface}.network", "w") as fh:
            fh.write(
                f"[Match]\nName={iface}\n\n[Network]\nUnmanaged=yes\n"
            )

    # ── Prevent dhclient leftovers ────────────────────────────────────────
    ifaces_d = "/etc/network/interfaces.d"
    if os.path.isdir(ifaces_d):
        for iface in (iface_co, iface_tg):
            path = os.path.join(ifaces_d, iface)
            bak  = path + ".bak"
            if os.path.isfile(path):
                os.rename(path, bak)
                ui.debug(f"  Renamed {path} -> {bak}")

    ui.success("Unmanaged interface configuration applied")


# ---------------------------------------------------------------------------
# LTE modem — NetworkManager profile
# ---------------------------------------------------------------------------

def configure_lte_nm_profile(config: dict, ui: UI, skipped: list) -> None:
    """
    Create a NetworkManager Ethernet connection for the LTE interface
    (eth1) and disable ModemManager so it does not interfere with the
    SIM7600G-H in RNDIS mode.
    """
    lte_if = get(config, "network", "lte_interface", default="eth1")

    # Disable ModemManager (conflicts with RNDIS modem — always enforce)
    ui.run("systemctl stop  ModemManager 2>/dev/null || true", check=False)
    ui.run("systemctl disable ModemManager 2>/dev/null || true", check=False)

    # Check if the NM connection already exists
    result = ui.run(
        f"nmcli -t -f NAME connection show 2>/dev/null | grep -qx '{lte_if}'",
        check=False,
    )
    if result.returncode == 0:
        ui.success(f"NetworkManager profile for {lte_if} already exists")
    else:
        ui.info(f"Creating NetworkManager profile for {lte_if} ...")
        ui.run(
            f"nmcli connection add type ethernet ifname {lte_if} "
            f"con-name {lte_if}",
            check=False,
        )
        ui.run(f"nmcli connection modify {lte_if} ipv4.method auto",            check=False)
        ui.run(f"nmcli connection modify {lte_if} ipv4.ignore-auto-dns no",     check=False)
        ui.run(f"nmcli connection modify {lte_if} connection.autoconnect yes",   check=False)
        ui.success(f"NetworkManager profile for {lte_if} created")

    # ── RNDIS mode + APN ────────────────────────────────────────────────────
    serial_dev = get(config, "lte", "serial_device", default="/dev/ttyUSB2")
    apn        = get(config, "lte", "apn", default="")
    _configure_modem(serial_dev, apn, ui, skipped)


# ---------------------------------------------------------------------------
# WireGuard — key pair + tunnel configuration
# ---------------------------------------------------------------------------

def setup_wireguard(config: dict, ui: UI, skipped: list) -> bool:
    """
    Set up the WireGuard tunnel for out-of-band VPN access.

    Key handling:
    * If ``wireguard.implant_private_key`` is provided in init.json it is
      used directly (the public key is derived from it).
    * If the field is empty, a fresh key pair is generated automatically.

    Endpoint is built from ``server_public_ip`` + ``server_port``.

    Returns True if wg0.conf was written (tunnel is ready), False otherwise.
    """
    wg_dir = "/etc/wireguard"
    os.makedirs(wg_dir, exist_ok=True)

    # Ensure wireguard-tools is available (may be missing if Step 1 was
    # skipped by idempotency or failed silently — exit 127 otherwise)
    if not shutil.which("wg"):
        ui.info("wg command not found — installing wireguard-tools ...")
        ui.run("apt-get install -y wireguard-tools", timeout=60)
        if not shutil.which("wg"):
            ui.warning("wireguard-tools installation failed — cannot continue")
            return False

    privkey_path = os.path.join(wg_dir, "private.key")
    pubkey_path  = os.path.join(wg_dir, "public.key")

    # ── Key handling ──────────────────────────────────────────────────────
    cfg_privkey = get(config, "wireguard", "implant_private_key", default="")

    if cfg_privkey:
        # User supplied a key — write it and derive the public half
        ui.info("Using implant private key from configuration ...")
        with open(privkey_path, "w") as fh:
            fh.write(cfg_privkey.strip() + "\n")
        os.chmod(privkey_path, 0o600)

        ui.run(
            f"wg pubkey < {privkey_path} > {pubkey_path}",
        )
        ui.success("WireGuard key pair set from configuration")
    elif not os.path.isfile(privkey_path):
        # No key supplied and none on disk — generate fresh
        ui.info("Generating WireGuard key pair ...")
        ui.run(
            f"wg genkey | tee {privkey_path} | wg pubkey > {pubkey_path}"
        )
        os.chmod(privkey_path, 0o600)
        ui.success("WireGuard key pair generated")
    else:
        ui.success("WireGuard key pair already exists on disk")

    with open(pubkey_path, "r") as fh:
        pubkey = fh.read().strip()
    ui.info(f"Implant public key: {pubkey}")
    ui.info("  -> Add this key to your WireGuard server's [Peer] block")

    # ── Tunnel configuration ──────────────────────────────────────────────
    srv_pubkey = get(config, "wireguard", "server_public_key", default="")
    srv_pub_ip = get(config, "wireguard", "server_public_ip",  default="")
    srv_port   = get(config, "wireguard", "server_port",       default=0)

    if not srv_pubkey or not srv_pub_ip or not srv_port:
        ui.skipped(
            "wg0.conf NOT generated — missing server_public_key, "
            "server_public_ip, or server_port"
        )
        skipped.append(
            "WireGuard tunnel not configured — fill wireguard.server_public_key, "
            "server_public_ip, and server_port in init.json and re-run setup"
        )
        return False

    implant_addr = get(config, "wireguard", "implant_address",      default="10.8.0.3/24")
    allowed_ips  = get(config, "wireguard", "allowed_ips",          default="10.8.0.0/24")
    keepalive    = get(config, "wireguard", "persistent_keepalive", default=25)
    lte_iface    = get(config, "network",   "lte_interface",        default="eth1")

    with open(privkey_path, "r") as fh:
        privkey = fh.read().strip()

    endpoint = f"{srv_pub_ip}:{srv_port}"

    ui.info("Writing /etc/wireguard/wg0.conf ...")
    wg_conf = (
        "[Interface]\n"
        f"PrivateKey = {privkey}\n"
        f"Address = {implant_addr}\n"
        f"PostUp = ip route add {srv_pub_ip} dev {lte_iface}\n"
        f"PreDown = ip route del {srv_pub_ip}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {srv_pubkey}\n"
        f"AllowedIPs = {allowed_ips}\n"
        f"Endpoint = {endpoint}\n"
        f"PersistentKeepalive = {keepalive}\n"
    )
    conf_path = os.path.join(wg_dir, "wg0.conf")
    with open(conf_path, "w") as fh:
        fh.write(wg_conf)
    os.chmod(conf_path, 0o600)

    # Enable at boot
    ui.run(
        "systemctl enable wg-quick@wg0.service 2>/dev/null || true",
        check=False,
    )
    ui.success("WireGuard configured and enabled at boot")
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _configure_modem(serial_dev: str, apn: str, ui: UI,
                     skipped: list) -> None:
    """
    Ensure the SIM7600G-H modem is in RNDIS mode and APN is set.

    Talks directly to the modem via AT commands over the serial port
    (no subprocess / modem-config.sh dependency — avoids the
    ``timeout cat`` buffering issues that plague shell-based AT I/O).
    """
    # ── Wait for modem serial port ────────────────────────────────────
    if not _wait_for_device(serial_dev, ui, retries=4, delay=5):
        skipped.append(
            f"LTE modem not detected — after connecting run:  "
            f"modem-config {serial_dev} set-rndis on"
        )
        return

    # ── Probe modem ───────────────────────────────────────────────────
    resp = _send_at(serial_dev, "AT", ui)
    if resp is None:
        ui.warning("Modem not responding to AT commands")
        skipped.append(
            f"LTE modem not responding — check {serial_dev} and run:  "
            f"modem-config {serial_dev} set-rndis on"
        )
        return

    # ── Check / enable RNDIS ──────────────────────────────────────────
    rndis_ok = False

    ui.info("Checking LTE modem RNDIS mode ...")
    resp = _send_at(serial_dev, "AT+CUSBPIDSWITCH?", ui)

    if resp and "9011" in resp:
        ui.success("LTE modem is in RNDIS mode (PID 9011)")
        rndis_ok = True
    else:
        pid = "unknown"
        if resp:
            import re
            m = re.search(r"(\d{4})", resp)
            if m:
                pid = m.group(1)
        ui.info(f"Modem is in mode PID {pid} — switching to RNDIS ...")
        _send_at(serial_dev, "AT+CUSBPIDSWITCH=9011,1,1", ui)

        # Modem reboots after USB PID switch — serial device vanishes
        # and re-enumerates.  Takes 15-25 s on the SIM7600G-H.
        ui.info("Waiting for modem to reboot after RNDIS switch ...")
        time.sleep(10)
        if not _wait_for_device(serial_dev, ui, retries=8, delay=5):
            ui.warning("Modem did not reappear — RNDIS will take effect "
                       "after system reboot")
        else:
            # Verify with retries (modem AT interface takes time to settle)
            for attempt in range(1, 6):
                time.sleep(5)
                ui.info(f"Verifying RNDIS mode (attempt {attempt}/5) ...")
                resp = _send_at(serial_dev, "AT+CUSBPIDSWITCH?", ui)
                if resp and "9011" in resp:
                    ui.success("LTE modem switched to RNDIS mode")
                    rndis_ok = True
                    break
            else:
                ui.warning("RNDIS enable sent but not confirmed yet — "
                           "it may take effect after system reboot")

    # ── Set APN ───────────────────────────────────────────────────────
    if not apn:
        skipped.append(
            "LTE APN not set — after setup run:  "
            f"modem-config {serial_dev} set-apn <your_apn>"
        )
        return

    if not rndis_ok:
        ui.info(f"APN to apply after modem is ready:")
        ui.info(f"  modem-config {serial_dev} set-apn {apn}")
        return

    ui.info(f"Setting APN to '{apn}' ...")
    for attempt in range(1, 6):
        resp = _send_at(serial_dev, f'AT+CGDCONT=1,"IP","{apn}"', ui)
        if resp is not None and "OK" in resp:
            ui.success(f"APN set to '{apn}'")
            return
        if attempt < 5:
            ui.info(f"APN set: retry {attempt}/5 in 3s ...")
            time.sleep(3)

    ui.warning(f"APN command failed — set manually:  "
               f"modem-config {serial_dev} set-apn {apn}")


# ---------------------------------------------------------------------------
# Low-level AT command interface
# ---------------------------------------------------------------------------

def _send_at(dev: str, cmd: str, ui: UI,
             timeout: float = 3.0) -> str | None:
    """
    Send an AT command to *dev* and return the response text.

    Opens the serial port, configures it to 115200 8N1 raw mode,
    flushes stale data, sends the command, and reads until ``OK``,
    ``ERROR``, or *timeout* seconds elapse.

    Returns the response string on success, or ``None`` if the
    device cannot be opened or no response is received.
    """
    try:
        fd = os.open(dev, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError as exc:
        ui.debug(f"Cannot open {dev}: {exc}")
        return None

    try:
        # ── Configure 115200 8N1 raw ──────────────────────────────────
        attrs = termios.tcgetattr(fd)
        # Input/output speed
        attrs[4] = termios.B115200  # ispeed
        attrs[5] = termios.B115200  # ospeed
        # Raw mode — disable all processing
        attrs[0] = 0           # iflag:  no parity/flow/mapping
        attrs[1] = 0           # oflag:  no output processing
        attrs[2] &= ~termios.PARENB   # cflag: no parity
        attrs[2] &= ~termios.CSTOPB   # cflag: 1 stop bit
        attrs[2] &= ~termios.CSIZE
        attrs[2] |= termios.CS8       # cflag: 8 data bits
        attrs[2] |= termios.CREAD | termios.CLOCAL
        attrs[3] = 0           # lflag:  no echo/canonical/signals
        # VMIN=0, VTIME=0 → pure non-blocking reads
        attrs[6][termios.VMIN]  = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)

        # Clear O_NONBLOCK for clean I/O (we use select for timeout)
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)

        # Flush any stale data in the receive buffer
        termios.tcflush(fd, termios.TCIFLUSH)

        # ── Send command ──────────────────────────────────────────────
        os.write(fd, (cmd + "\r").encode())

        # ── Read response ─────────────────────────────────────────────
        buf = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.1))
            if ready:
                chunk = os.read(fd, 1024)
                if chunk:
                    buf += chunk
                    text = buf.decode(errors="replace")
                    # Stop as soon as we see a final result code
                    if "OK" in text or "ERROR" in text:
                        return text

        # Return whatever we got (may be partial or empty)
        text = buf.decode(errors="replace").strip()
        return text if text else None

    except (OSError, termios.error) as exc:
        ui.debug(f"Serial error on {dev}: {exc}")
        return None
    finally:
        os.close(fd)


def _wait_for_device(dev: str, ui: UI, retries: int = 4,
                     delay: int = 5) -> bool:
    """Poll for a character device to appear.  Returns True if found."""
    for attempt in range(1, retries + 1):
        if os.path.exists(dev):
            return True
        ui.info(f"Waiting for {dev} ({attempt}/{retries}) ...")
        time.sleep(delay)
    ui.info(f"{dev} not found after {retries * delay}s")
    return False
