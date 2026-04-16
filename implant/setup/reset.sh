#!/bin/bash
# =========================================================================
# PhantomPi — System Reset
# =========================================================================
# Undoes everything init.py creates so the script can be re-run from
# scratch on the same SD card without re-imaging.
#
# Usage:
#   sudo bash setup/reset.sh           # quick reset (keeps WG keys)
#   sudo bash setup/reset.sh --full    # remove everything including keys
#
# What is NOT removed (safe to leave for re-runs):
#   - APT packages (reinstalling them is slow and idempotent)
#   - pip packages (same reason)
#   - cmdline.txt changes (idempotent — init.py checks before appending)
# =========================================================================

set -euo pipefail

RED='\033[91m'
GREEN='\033[92m'
YELLOW='\033[93m'
CYAN='\033[96m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "  ${CYAN}[*]${RESET} $1"; }
success() { echo -e "  ${GREEN}[+]${RESET} $1"; }
warn()    { echo -e "  ${YELLOW}[!]${RESET} $1"; }

# Wait for modem serial device to become available (it disappears during reboot)
wait_for_modem() {
    local dev="$1" retries="${2:-6}" delay="${3:-5}"
    for i in $(seq 1 "$retries"); do
        [ -c "$dev" ] && return 0
        info "Modem not ready, waiting... ($i/$retries)"
        sleep "$delay"
    done
    return 1
}

# Send AT command with retries (device may vanish mid-reboot)
send_at() {
    local dev="$1" cmd="$2" retries="${3:-3}" delay="${4:-5}"
    for i in $(seq 1 "$retries"); do
        if [ -c "$dev" ]; then
            stty -F "$dev" 115200 raw -echo 2>/dev/null || true
            echo -e "${cmd}\r" > "$dev" 2>/dev/null && return 0
        fi
        [ "$i" -lt "$retries" ] && { info "Retry $i/$retries in ${delay}s ..."; sleep "$delay"; }
    done
    return 1
}

# ── Root check ────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo -e "  ${RED}[-]${RESET} Run as root:  sudo bash setup/reset.sh"
    exit 1
fi

FULL=false
[ "${1:-}" = "--full" ] && FULL=true

echo
echo -e "${CYAN}${BOLD}========================================${RESET}"
echo -e "${CYAN}${BOLD}  PhantomPi — System Reset${RESET}"
echo -e "${CYAN}${BOLD}========================================${RESET}"
echo

# ── 1. Stop & disable all implant services and timers ─────────────────────
info "Stopping implant services and timers ..."

UNITS=(
    wg-keepalive.timer  wg-keepalive.service
    bridge-sync.timer   bridge-sync.service
    power-monitor.timer power-monitor.service
    cred-analyzer.timer cred-analyzer.service
    implant-api.service
    packet-sniffer.service
    hidden-hotspot.service
    wg-quick@wg0.service
)

for unit in "${UNITS[@]}"; do
    systemctl stop    "$unit" 2>/dev/null || true
    systemctl disable "$unit" 2>/dev/null || true
done
success "Services stopped and disabled"

# ── 2. Remove systemd unit symlinks ──────────────────────────────────────
info "Removing systemd unit registrations ..."

UNITS=(
    bridge-sync.service   bridge-sync.timer
    implant-api.service
    hidden-hotspot.service
    cred-analyzer.service cred-analyzer.timer
    packet-sniffer.service
    power-monitor.service power-monitor.timer
    wg-keepalive.service  wg-keepalive.timer
)

for unit in "${UNITS[@]}"; do
    systemctl disable "$unit" 2>/dev/null || true
    systemctl unlink  "$unit" 2>/dev/null || true
done
systemctl daemon-reload
success "Systemd units disabled and unlinked"

# ── 3. Remove /opt/implant/ ──────────────────────────────────────────────
info "Removing /opt/implant/ ..."

if [ -d /opt/implant ]; then
    rm -rf /opt/implant
    success "Removed /opt/implant/"
else
    success "/opt/implant/ does not exist — nothing to remove"
fi

# ── 4. Remove udev rules ─────────────────────────────────────────────────
info "Removing udev rules ..."
rm -f /etc/udev/rules.d/10-persistent-net.rules
udevadm control --reload 2>/dev/null || true
success "udev rules removed"

# ── 5. Remove NetworkManager drop-ins ─────────────────────────────────────
info "Removing NetworkManager configuration ..."
rm -f /etc/NetworkManager/conf.d/unmanaged.conf

# Remove the ttyUSB block appended to NetworkManager.conf
if [ -f /etc/NetworkManager/NetworkManager.conf ]; then
    sed -i '/# PhantomPi/,+2d' /etc/NetworkManager/NetworkManager.conf 2>/dev/null || true
fi

# Remove systemd-networkd drop-ins
rm -f /etc/systemd/network/10-eth0.network
rm -f /etc/systemd/network/10-eth2.network

# Restore dhclient interface backups
shopt -s nullglob
for bak in /etc/network/interfaces.d/*.bak; do
    mv "$bak" "${bak%.bak}"
done
shopt -u nullglob

success "NetworkManager configuration removed"

# ── 6. Remove NM connection profiles & restore ModemManager ──────────────
info "Removing NetworkManager connections ..."
nmcli connection delete eth1      2>/dev/null || true
nmcli connection delete berry_ap  2>/dev/null || true

# Re-enable ModemManager (disabled by setup)
systemctl enable ModemManager 2>/dev/null || true
success "NM connections removed, ModemManager re-enabled"

# ── 7. Remove WireGuard configuration ────────────────────────────────────
info "Removing WireGuard configuration ..."
rm -f /etc/wireguard/wg0.conf

if [ "$FULL" = true ]; then
    rm -f /etc/wireguard/private.key
    rm -f /etc/wireguard/public.key
    success "WireGuard config + keys removed (--full)"
else
    warn "WireGuard keys preserved at /etc/wireguard/ (use --full to remove)"
    success "WireGuard wg0.conf removed"
fi

# ── 8. Remove boot hardening artefacts ───────────────────────────────────
info "Removing boot hardening ..."
rm -f /etc/modprobe.d/blacklist-bluetooth.conf

# Re-enable bluetooth (will take effect after reboot)
systemctl enable hciuart.service   2>/dev/null || true
systemctl enable bluetooth.service 2>/dev/null || true

# Remove bcm2835_wdt from /etc/modules
if [ -f /etc/modules ]; then
    sed -i '/^bcm2835_wdt$/d' /etc/modules
fi

# Disable watchdog service
systemctl disable watchdog 2>/dev/null || true

# Remove watchdog.conf PhantomPi additions
if [ -f /etc/watchdog.conf ]; then
    sed -i '/# PhantomPi/,+2d' /etc/watchdog.conf 2>/dev/null || true
fi

success "Boot hardening removed"

# ── 9. Remove logrotate configs ──────────────────────────────────────────
info "Removing logrotate configurations ..."
rm -f /etc/logrotate.d/bridge-sync
rm -f /etc/logrotate.d/cred-analyzer
rm -f /etc/logrotate.d/wg-keepalive
rm -f /etc/logrotate.d/power-monitor
success "Logrotate configs removed"

# ── 10. Remove helper symlinks ───────────────────────────────────────────
info "Removing helper symlinks ..."
rm -f /usr/local/bin/hidden-hotspot
rm -f /usr/local/bin/modem-config
rm -f /usr/local/bin/spoof-target
success "Helper symlinks removed"

# ── 11. Full-mode extras ─────────────────────────────────────────────────
if [ "$FULL" = true ]; then
    info "Cleaning cred-analyzer logs ..."
    rm -rf /opt/implant/logs/cred-analyzer
    success "Cred-analyzer logs removed"
fi

# ── 12. Witty Pi — uninstall via official script & clear hardware ─────────
info "Resetting Witty Pi ..."

# Kill the daemon if it is running
pkill -f "wittypi/daemon.sh"  2>/dev/null || true
pkill -f "wittyPi/daemon.sh"  2>/dev/null || true

WITTYPI_DIR="/opt/implant/wittypi"

# Prefer the official uninstall.sh when available
if [ -f "$WITTYPI_DIR/uninstall.sh" ]; then
    info "Running official Witty Pi uninstall.sh ..."
    cd "$WITTYPI_DIR" && yes | bash uninstall.sh 2>/dev/null || true
    cd /
    success "Official uninstall script executed"
else
    # Manual fallback — remove init.d entries ourselves
    if [ -f /etc/init.d/wittypi ]; then
        update-rc.d -f wittypi remove 2>/dev/null || true
        rm -f /etc/init.d/wittypi
    fi
    update-rc.d -f uwi remove 2>/dev/null || true
    rm -f /etc/init.d/uwi 2>/dev/null || true
    success "Witty Pi daemon unregistered (manual fallback)"
fi

# Remove crontab entries the vendor installer may have added
crontab -l 2>/dev/null | grep -v "wittypi\|wittyPi" | crontab - 2>/dev/null || true

# Remove schedule files
if [ -d "$WITTYPI_DIR" ]; then
    rm -f "$WITTYPI_DIR/schedule.wpi" 2>/dev/null || true
    rm -f "$WITTYPI_DIR/schedules/"*.wpi 2>/dev/null || true
fi

# Clear MCU registers via I2C (Witty Pi 4 MCU is on bus 1, address 0x08)
# The official uninstall does NOT reset hardware state, so we must do it.
# Register map from Witty Pi 4 User Manual rev 1.04:
#   #17       = power-on default state  (0 = default-off / button-press boot)
#   #27-#31   = ALARM1 data (scheduled startup)
#   #32-#36   = ALARM2 data (scheduled shutdown)
#   #39-#40   = alarm triggered flags
if command -v i2cset &>/dev/null; then
    info "Clearing Witty Pi MCU registers (I2C 0x08) ..."

    # Reg 17: power-on default state = 0 (default-off, button-press only)
    # Uses Witty Pi's own i2c_write (write + verify + retry) instead of raw i2cset
    if [ -f /opt/implant/wittypi/wittypi/utilities.sh ]; then
        (cd /opt/implant/wittypi/wittypi && source utilities.sh && i2c_write 0x01 $I2C_MC_ADDRESS $I2C_CONF_DEFAULT_ON 0x00) 2>/dev/null || true
    else
        i2cset -y 1 0x08 17 0x00 2>/dev/null || true
    fi

    # Regs 27-31: ALARM1 (scheduled startup) — clear all 5 bytes
    for reg in 27 28 29 30 31; do
        i2cset -y 1 0x08 "$reg" 0x00 2>/dev/null || true
    done

    # Regs 32-36: ALARM2 (scheduled shutdown) — clear all 5 bytes
    for reg in 32 33 34 35 36; do
        i2cset -y 1 0x08 "$reg" 0x00 2>/dev/null || true
    done

    # Regs 39-40: alarm triggered flags — clear both
    i2cset -y 1 0x08 39 0x00 2>/dev/null || true
    i2cset -y 1 0x08 40 0x00 2>/dev/null || true

    success "Witty Pi schedule cleared (default: button-press boot only)"
else
    warn "i2c-tools not available — cannot clear Witty Pi MCU registers"
fi

success "Witty Pi reset complete"

# ── 13. LTE modem — disable RNDIS mode and clear APN ────────────────────
info "Resetting LTE modem to factory defaults ..."
SERIAL_DEV="/dev/ttyUSB2"

if wait_for_modem "$SERIAL_DEV" 3 3; then
    # Clear APN (reset to empty)
    if send_at "$SERIAL_DEV" 'AT+CGDCONT=1,"IP",""' 3 5; then
        success "APN cleared"
    else
        warn "Failed to clear APN"
    fi
    sleep 2

    # Disable RNDIS mode — switch back to default USB PID (9001)
    # This triggers a modem reboot — the serial device will vanish.
    if send_at "$SERIAL_DEV" 'AT+CUSBPIDSWITCH=9001,1,1' 3 5; then
        success "RNDIS disable command sent (modem will reboot)"
    else
        warn "Failed to send RNDIS disable command"
    fi
else
    warn "Modem serial device $SERIAL_DEV not found — skipping modem reset"
fi

# ── 14. Rebuild initramfs ────────────────────────────────────────────────
info "Rebuilding initramfs ..."
update-initramfs -u 2>/dev/null || true
success "initramfs rebuilt"

# ── Done ──────────────────────────────────────────────────────────────────
echo
echo -e "${CYAN}${BOLD}========================================${RESET}"
echo -e "${GREEN}${BOLD}  Reset complete${RESET}"
echo -e "${CYAN}${BOLD}========================================${RESET}"
echo
echo -e "  Ready for a fresh run:"
echo -e "    ${BOLD}sudo bash setup.sh${RESET}"
echo

if [ "$FULL" != true ]; then
    echo -e "  ${YELLOW}Preserved (use --full to remove):${RESET}"
    echo -e "    - WireGuard keys (/etc/wireguard/private.key, public.key)"
    echo -e "    - APT/pip packages"
    echo
fi
