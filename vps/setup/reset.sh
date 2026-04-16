#!/bin/bash
# =========================================================================
# VPS WireGuard & OpenClaw — System Reset
# =========================================================================
# Undoes everything init.py creates so the script can be re-run from
# scratch without re-imaging the VPS.
#
# Usage:
#   sudo bash setup/reset.sh           # quick reset (keeps WG keys)
#   sudo bash setup/reset.sh --full    # remove everything including keys
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

if [ "$(id -u)" -ne 0 ]; then
    echo -e "  ${RED}[-]${RESET} Run as root:  sudo bash setup/reset.sh"
    exit 1
fi

FULL=false
[ "${1:-}" = "--full" ] && FULL=true

echo
echo -e "${CYAN}${BOLD}========================================${RESET}"
echo -e "${CYAN}${BOLD}  VPS WireGuard & OpenClaw — System Reset${RESET}"
echo -e "${CYAN}${BOLD}========================================${RESET}"
echo

# ── 1. Stop & remove legacy Discord bot (if any) ────────────────────────
info "Stopping legacy Discord bot service (if any) ..."
systemctl stop    discord-bot.service 2>/dev/null || true
systemctl disable discord-bot.service 2>/dev/null || true
rm -f /etc/systemd/system/discord-bot.service
success "Legacy Discord bot cleaned up"

# ── 2. Stop OpenClaw ────────────────────────────────────────────────────
info "Stopping OpenClaw ..."
if command -v openclaw &>/dev/null; then
    openclaw daemon stop 2>/dev/null || true
    openclaw daemon uninstall 2>/dev/null || true
    success "OpenClaw daemon stopped"
else
    success "OpenClaw not installed — nothing to stop"
fi

# ── 3. Remove OpenClaw data ─────────────────────────────────────────────
info "Removing /opt/openclaw/ ..."
if [ -d "/opt/openclaw" ]; then
    rm -rf /opt/openclaw
    success "Removed /opt/openclaw/"
else
    success "/opt/openclaw does not exist"
fi

if [ "$FULL" = true ]; then
    info "Removing ~/.openclaw/ (--full) ..."
    rm -rf ~/.openclaw
    success "Removed ~/.openclaw/"
else
    warn "~/.openclaw/ preserved (use --full to remove config & skills)"
fi

# ── 4. Remove legacy /opt/implant/ (old discord bot) ────────────────────
info "Removing /opt/implant/ ..."
if [ -d "/opt/implant" ]; then
    rm -rf /opt/implant
    success "Removed /opt/implant/"
else
    success "/opt/implant does not exist"
fi

systemctl daemon-reload 2>/dev/null || true

# ── 5. Stop & disable WireGuard ─────────────────────────────────────────
info "Stopping WireGuard ..."
systemctl stop    wg-quick@wg0.service 2>/dev/null || true
systemctl disable wg-quick@wg0.service 2>/dev/null || true
success "WireGuard stopped and disabled"

# ── 6. Remove WireGuard configuration ───────────────────────────────────
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

# ── 7. Remove IP forwarding config ──────────────────────────────────────
info "Removing IP forwarding configuration ..."
rm -f /etc/sysctl.d/99-wireguard.conf
sysctl -w net.ipv4.ip_forward=0 2>/dev/null || true
success "IP forwarding disabled"

# ── Done ────────────────────────────────────────────────────────────────
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
    echo -e "    - OpenClaw config (~/.openclaw/)"
    echo -e "    - APT packages"
    echo
fi
