#!/bin/bash
# =========================================================================
# VPS WireGuard & Discord Bot — System Reset
# =========================================================================
# Undoes everything init.py creates so the script can be re-run from
# scratch without re-imaging the VPS.
#
# Usage:
#   sudo bash setup/reset.sh           # quick reset (keeps WG keys)
#   sudo bash setup/reset.sh --full    # remove everything including keys
#
# What is NOT removed (safe to leave for re-runs):
#   - APT packages (reinstalling them is slow and idempotent)
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

# ── Root check ────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo -e "  ${RED}[-]${RESET} Run as root:  sudo bash setup/reset.sh"
    exit 1
fi

FULL=false
[ "${1:-}" = "--full" ] && FULL=true

IMPLANT_DIR="/opt/implant"

echo
echo -e "${CYAN}${BOLD}========================================${RESET}"
echo -e "${CYAN}${BOLD}  VPS WireGuard & Discord Bot — System Reset${RESET}"
echo -e "${CYAN}${BOLD}========================================${RESET}"
echo

# ── 1. Stop & disable Discord bot service ─────────────────────────────────
info "Stopping Discord bot service ..."
systemctl stop    discord-bot.service 2>/dev/null || true
systemctl disable discord-bot.service 2>/dev/null || true
rm -f /etc/systemd/system/discord-bot.service
systemctl daemon-reload 2>/dev/null || true
success "Discord bot service stopped and removed"

# ── 2. Remove /opt/implant/ ──────────────────────────────────────────────
info "Removing $IMPLANT_DIR ..."
if [ -d "$IMPLANT_DIR" ]; then
    rm -rf "$IMPLANT_DIR"
    success "Removed $IMPLANT_DIR"
else
    success "$IMPLANT_DIR does not exist — nothing to remove"
fi

# ── 3. Stop & disable WireGuard ──────────────────────────────────────────
info "Stopping WireGuard ..."
systemctl stop    wg-quick@wg0.service 2>/dev/null || true
systemctl disable wg-quick@wg0.service 2>/dev/null || true
success "WireGuard stopped and disabled"

# ── 4. Remove WireGuard configuration ────────────────────────────────────
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

# ── 5. Remove IP forwarding config ───────────────────────────────────────
info "Removing IP forwarding configuration ..."
rm -f /etc/sysctl.d/99-wireguard.conf
sysctl -w net.ipv4.ip_forward=0 2>/dev/null || true
success "IP forwarding disabled"

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
    echo -e "    - APT packages (wireguard-tools, python3-venv)"
    echo
fi
