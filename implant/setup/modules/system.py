"""
PhantomPi Setup — System-Level Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* APT package installation
* Boot-stall prevention (Bluetooth blacklist, serial console removal)
* Hardware watchdog (bcm2835_wdt)
"""

from __future__ import annotations

import os
import re

from .ui import UI


# ---------------------------------------------------------------------------
# APT packages required by the implant
# ---------------------------------------------------------------------------
APT_PACKAGES = [
    # Networking & bridge
    "bridge-utils", "ethtool", "ebtables", "arptables", "iptables",
    "net-tools", "tcpdump", "tshark", "curl", "dnsutils",
    # WireGuard
    "wireguard", "wireguard-tools",
    # LTE modem
    "minicom",
    # Watchdog
    "watchdog",
    # Python
    "python3-venv", "python3-pip", "python3-scapy",
    # TLS certificate generation
    "openssl",
    # Log management
    "logrotate",
    # Network management
    "network-manager",
    # BruteShark build dependencies
    "libicu-dev", "icu-devtools", "git",
    # Witty Pi 4 (I2C communication with MCU)
    "i2c-tools",
]

# Bluetooth kernel modules to blacklist (cause boot stalls on the Pi)
_BT_MODULES = [
    "btbcm", "hci_uart", "bluetooth",
    "rfcomm", "btintel", "btrtl", "btusb",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install_packages(ui: UI) -> None:
    """Install every APT package the implant needs (skips when all present)."""
    total = len(APT_PACKAGES)

    # Quick pre-check: count already-installed packages
    ui.info("Checking installed packages ...")
    result = ui.run(
        "dpkg-query -W -f='${Status}\\n' "
        + " ".join(APT_PACKAGES)
        + " 2>/dev/null",
        check=False,
    )
    installed = (
        result.stdout.count("install ok installed") if result.stdout else 0
    )

    if installed >= total:
        ui.success(f"All {total} system packages already installed")
    else:
        ui.info(f"{total - installed} of {total} packages need installing ...")
        ui.run("apt-get update -qq", timeout=120)
        pkg_str = " ".join(APT_PACKAGES)
        ui.run(
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {pkg_str}",
            timeout=600,
        )
        ui.success("System packages installed")

    # Python libs needed by bruteshark.py wrapper (python-dotenv, requests)
    result = ui.run(
        "python3 -c 'import dotenv; import requests' 2>/dev/null",
        check=False,
    )
    if result.returncode == 0:
        ui.success("Python helper libraries already installed")
    else:
        ui.info("Installing Python helper libraries ...")
        ui.run(
            "pip3 install python-dotenv requests "
            "--break-system-packages -q 2>/dev/null "
            "|| pip3 install python-dotenv requests -q",
            check=False,
        )
        ui.success("Python dependencies installed")


def harden_boot(ui: UI) -> None:
    """
    Prevent the two most common Raspberry Pi boot stalls:
    1. Bluetooth kernel-module load delays  ->  blacklist the modules
    2. UART serial-console initialisation   ->  strip it from cmdline.txt
    Also ensures ``net.ifnames=0 biosdevname=0`` is on the kernel cmdline.
    """
    # ── 1. Bluetooth blacklist ────────────────────────────────────────────
    ui.info("Blacklisting Bluetooth kernel modules ...")
    bl_path = "/etc/modprobe.d/blacklist-bluetooth.conf"
    with open(bl_path, "w") as fh:
        fh.write(
            "# PhantomPi — disable Bluetooth to avoid boot stalls\n"
            + "\n".join(f"blacklist {m}" for m in _BT_MODULES)
            + "\n"
        )
    ui.run("systemctl disable hciuart.service  2>/dev/null || true", check=False)
    ui.run("systemctl disable bluetooth.service 2>/dev/null || true", check=False)
    ui.success("Bluetooth modules blacklisted")

    # ── 2. Kernel command line (serial console + predictable naming) ──────
    for candidate in ("/boot/firmware/cmdline.txt", "/boot/cmdline.txt"):
        if os.path.isfile(candidate):
            cmdline_path = candidate
            break
    else:
        ui.warning("cmdline.txt not found — skipping serial-console removal")
        return

    ui.info(f"Patching {cmdline_path} ...")
    with open(cmdline_path, "r") as fh:
        original = fh.read().strip()

    line = original
    # Remove serial-console arguments
    line = re.sub(r"\bconsole=serial0,\d+\s*", "", line)
    line = re.sub(r"\bconsole=ttyAMA0,\d+\s*", "", line)
    # Ensure predictable-naming is disabled
    if "net.ifnames=0" not in line:
        line += " net.ifnames=0"
    if "biosdevname=0" not in line:
        line += " biosdevname=0"
    line = " ".join(line.split())  # normalise whitespace

    if line != original:
        with open(cmdline_path, "w") as fh:
            fh.write(line + "\n")
        ui.success("Boot command line patched")
    else:
        ui.success("Boot command line already clean")


def setup_watchdog(ui: UI) -> None:
    """
    Enable the Broadcom SoC hardware watchdog so the Pi auto-resets on
    kernel panics or hard hangs.
    """
    ui.info("Configuring hardware watchdog ...")

    # Load module at boot
    modules_path = "/etc/modules"
    if os.path.isfile(modules_path):
        with open(modules_path, "r") as fh:
            content = fh.read()
        if "bcm2835_wdt" not in content:
            with open(modules_path, "a") as fh:
                fh.write("bcm2835_wdt\n")

    # watchdog.conf — ensure the device is set
    wdconf = "/etc/watchdog.conf"
    if os.path.isfile(wdconf):
        with open(wdconf, "r") as fh:
            content = fh.read()
        needs_device = (
            "watchdog-device" not in content
            or content.count("#watchdog-device") == content.count("watchdog-device")
        )
        if needs_device:
            with open(wdconf, "a") as fh:
                fh.write(
                    "\n# PhantomPi — hardware watchdog\n"
                    "watchdog-device = /dev/watchdog\n"
                    "watchdog-timeout = 15\n"
                )

    ui.run("systemctl enable watchdog 2>/dev/null || true", check=False)
    ui.success("Hardware watchdog enabled")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write(path: str, content: str, *, mode: int | None = None) -> None:
    """Write *content* to *path*, optionally setting file mode."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    if mode is not None:
        os.chmod(path, mode)
