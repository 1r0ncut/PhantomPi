#!/usr/bin/env python3
"""
PhantomPi — Automated Implant Setup
=====================================
Provisions a fresh Kali Linux ARM image on a Raspberry Pi 4 as a
fully operational PhantomPi red-team implant.

Usage
-----
    sudo bash setup.sh                           # default config
    sudo bash setup.sh -c my_config.json         # custom config
    sudo bash setup.sh --debug                   # verbose output
    sudo bash setup.sh --skip-bruteshark         # skip .NET build

The script reads all deployment parameters from ``setup/init.json``
(or a user-supplied path).  Fields left empty are skipped; a final
summary reminds the operator what still needs attention.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

# ---------------------------------------------------------------------------
# Path setup — works no matter where the repo was cloned
# ---------------------------------------------------------------------------
SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR  = os.path.dirname(SETUP_DIR)
sys.path.insert(0, SETUP_DIR)

from modules.ui      import UI                                   # noqa: E402
from modules.config  import load_config, validate_config         # noqa: E402
from modules         import system, network, deploy, services    # noqa: E402

# Total major steps displayed in the progress header
TOTAL_STEPS = 9


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def _check_root(ui: UI) -> None:
    """Abort immediately if not running as root."""
    if os.geteuid() != 0:
        ui.error("This script must be run as root.  Use:  sudo bash setup.sh")
        sys.exit(1)
    ui.success("Running as root")


def _check_platform(ui: UI) -> None:
    """Warn (but continue) if we are not on a Raspberry Pi / ARM Linux."""
    import platform
    machine = platform.machine()
    if machine not in ("aarch64", "armv7l"):
        ui.warning(
            f"Detected architecture '{machine}' — expected aarch64 (Raspberry Pi 4). "
            "Proceeding, but some steps may fail."
        )
    else:
        ui.success(f"Platform OK ({machine})")


# ---------------------------------------------------------------------------
# Fail-safe step runner
# ---------------------------------------------------------------------------

def _try(ui: UI, label: str, fn, failures: list, debug: bool):
    """
    Execute *fn()* inside a try/except.  On failure, log the error and
    append a human-readable message to *failures* so the final summary
    can report it.  Returns whatever *fn()* returns, or ``None`` on error.
    """
    try:
        return fn()
    except Exception as exc:
        ui.error(f"{label}: {exc}")
        failures.append(f"{label} — {exc}")
        if debug:
            for line in traceback.format_exc().splitlines():
                ui.debug(line)
        return None


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main() -> None:
    # ── Argument parser ───────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        prog="phantompi-setup",
        description="PhantomPi — Automated Implant Setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  sudo bash setup.sh\n"
            "  sudo bash setup.sh -c /path/to/config.json\n"
            "  sudo bash setup.sh --debug\n"
            "  sudo bash setup.sh --skip-bruteshark\n"
        ),
    )
    parser.add_argument(
        "-c", "--config",
        default=os.path.join(SETUP_DIR, "init.json"),
        help="path to the JSON configuration file (default: setup/init.json)",
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="enable verbose debug output for every command",
    )
    parser.add_argument(
        "--skip-bruteshark",
        action="store_true",
        help="skip BruteShark installation (requires .NET 3.1 SDK, time-consuming)",
    )
    args = parser.parse_args()

    # ── UI + banner ───────────────────────────────────────────────────────
    ui = UI(debug_mode=args.debug)
    ui.banner()

    # ── Pre-flight checks ─────────────────────────────────────────────────
    _check_root(ui)
    _check_platform(ui)

    # ── Load & validate configuration ─────────────────────────────────────
    ui.info(f"Loading configuration from {args.config} ...")
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        ui.error(f"Configuration file not found: {args.config}")
        ui.info("Copy setup/init.json, fill in your values, and re-run.")
        sys.exit(1)
    except Exception as exc:
        ui.error(f"Failed to parse configuration: {exc}")
        sys.exit(1)
    ui.success("Configuration loaded")

    warnings = validate_config(config)
    if warnings:
        ui.warning("Configuration has empty fields — affected features "
                    "will be skipped:")
        for w in warnings:
            ui.warning(f"  - {w}")

    # Items that were skipped (empty config) vs. items that failed (errors)
    skipped:  list[str] = []
    failures: list[str] = []

    # ── Safety: stop wg-keepalive in case this is a re-run ────────────────
    ui.info("Stopping wg-keepalive.timer (safety measure) ...")
    ui.run("systemctl stop wg-keepalive.timer  2>/dev/null || true", check=False)
    ui.run("systemctl stop wg-keepalive.service 2>/dev/null || true", check=False)

    # ==================================================================
    #  STEP 1 — System Packages
    # ==================================================================
    ui.step(1, TOTAL_STEPS, "System Packages")
    _try(ui, "Package installation", lambda: system.install_packages(ui),
         failures, args.debug)

    # ==================================================================
    #  STEP 2 — Deploy Implant Files
    # ==================================================================
    ui.step(2, TOTAL_STEPS, "Deploy Implant Files")
    _try(ui, "File deployment",
         lambda: deploy.deploy_files(REPO_DIR, ui), failures, args.debug)
    _try(ui, "Log directory creation",
         lambda: deploy.create_log_dirs(ui), failures, args.debug)
    _try(ui, "Script permissions",
         lambda: deploy.set_permissions(ui), failures, args.debug)
    _try(ui, "config.env generation",
         lambda: deploy.generate_config_env(config, ui), failures, args.debug)

    # ==================================================================
    #  STEP 3 — System Hardening
    # ==================================================================
    ui.step(3, TOTAL_STEPS, "System Hardening")
    _try(ui, "Boot hardening",
         lambda: system.harden_boot(ui), failures, args.debug)
    _try(ui, "Watchdog setup",
         lambda: system.setup_watchdog(ui), failures, args.debug)

    # ==================================================================
    #  STEP 4 — Network Configuration
    # ==================================================================
    ui.step(4, TOTAL_STEPS, "Network Configuration")
    _try(ui, "udev rules",
         lambda: network.configure_udev_rules(config, ui), failures, args.debug)
    _try(ui, "NM unmanaged interfaces",
         lambda: network.configure_nm_unmanaged(config, ui), failures, args.debug)
    _try(ui, "LTE modem profile",
         lambda: network.configure_lte_nm_profile(config, ui, skipped),
         failures, args.debug)

    # ==================================================================
    #  STEP 5 — WireGuard VPN
    # ==================================================================
    ui.step(5, TOTAL_STEPS, "WireGuard VPN")
    wg_configured = _try(
        ui, "WireGuard configuration",
        lambda: network.setup_wireguard(config, ui, skipped),
        failures, args.debug,
    ) or False  # ensure bool even on failure

    # ==================================================================
    #  STEP 6 — Discord API Server
    # ==================================================================
    ui.step(6, TOTAL_STEPS, "Discord API Server")
    _try(ui, "Discord API setup",
         lambda: services.setup_discord_api(config, ui, skipped),
         failures, args.debug)

    # ==================================================================
    #  STEP 7 — BruteShark Credential Extractor
    # ==================================================================
    ui.step(7, TOTAL_STEPS, "BruteShark Credential Extractor")
    bs_ok = _try(
        ui, "BruteShark installation",
        lambda: services.setup_bruteshark(ui, skip=args.skip_bruteshark),
        failures, args.debug,
    )
    if bs_ok is False and not args.skip_bruteshark:
        skipped.append(
            "BruteShark build failed — install manually later (see wiki)"
        )

    # ==================================================================
    #  STEP 8 — Systemd Services & Log Rotation
    # ==================================================================
    ui.step(8, TOTAL_STEPS, "Systemd Services & Log Rotation")
    _try(ui, "Systemd unit configuration",
         lambda: services.configure_systemd(ui, wg_configured=wg_configured),
         failures, args.debug)
    _try(ui, "Logrotate configuration",
         lambda: services.configure_logrotate(ui), failures, args.debug)

    # ==================================================================
    #  STEP 9 — Finalize
    # ==================================================================
    ui.step(9, TOTAL_STEPS, "Finalize")
    _try(ui, "Hotspot creation",
         lambda: services.create_hotspot(config, ui, skipped),
         failures, args.debug)
    _try(ui, "Helper symlinks",
         lambda: deploy.create_helper_symlinks(ui), failures, args.debug)

    _try(ui, "Witty Pi installation",
         lambda: services.setup_wittypi(config, ui), failures, args.debug)

    # Update initramfs to apply bluetooth-blacklist + udev rules
    ui.info("Updating initramfs ...")
    ui.run("update-initramfs -u 2>/dev/null || true", check=False, timeout=120)
    ui.success("initramfs updated")

    # ==================================================================
    #  SUMMARY
    # ==================================================================
    ui.summary(skipped, failures)

    if failures:
        ui.info("Some steps FAILED — fix the issues above then re-run:")
        print("    sudo bash setup.sh")
        print()
        ui.info("Or reset and start fresh:")
        print("    sudo bash setup/reset.sh")
        print("    sudo bash setup.sh")
    elif skipped:
        ui.info("Complete the pending items listed above, then reboot:")
        print("    sudo reboot")
    else:
        ui.info("All done.  Reboot the implant to activate everything:")
        print("    sudo reboot")
    print()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("  \033[93m[!]\033[0m Setup interrupted — re-run to resume:")
        print("      sudo bash setup.sh")
        print()
        sys.exit(130)
