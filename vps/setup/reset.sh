#!/bin/bash
# =========================================================================
# VPS WireGuard & OpenClaw — System Reset
# =========================================================================
# Undoes everything setup.sh creates so the script can be re-run from
# scratch without re-imaging the VPS.
#
# Usage:
#   sudo bash setup/reset.sh           # quick reset (keeps WG keys, OpenClaw binary, user)
#   sudo bash setup/reset.sh --full    # full reset (removes everything including keys)
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

# ── 2. Stop & remove OpenClaw gateway service ───────────────────────────
info "Stopping OpenClaw gateway service ..."
systemctl stop    openclaw-gateway.service 2>/dev/null || true
systemctl disable openclaw-gateway.service 2>/dev/null || true
rm -f /etc/systemd/system/openclaw-gateway.service
systemctl daemon-reload 2>/dev/null || true
success "OpenClaw gateway service removed"

# ── 3. Remove OpenClaw skills ────────────────────────────────────────────
info "Removing /home/openclaw/skills/ ..."
rm -rf /home/openclaw/skills
success "Removed /home/openclaw/skills/"

# ── 4. Full: remove OpenClaw binary, config, and system user ────────────
if [ "$FULL" = true ]; then
    info "Removing OpenClaw binary (--full) ..."
    npm uninstall -g openclaw 2>/dev/null || true
    # Belt-and-suspenders: remove binary directly if npm missed it
    rm -f /usr/local/bin/openclaw /usr/bin/openclaw 2>/dev/null || true
    success "OpenClaw package removed"

    info "Removing OpenClaw config and user (--full) ..."
    # Disable linger before removing the user
    loginctl disable-linger openclaw 2>/dev/null || true
    # Remove user and home directory (/home/openclaw)
    if id openclaw &>/dev/null; then
        userdel -r openclaw 2>/dev/null || true
        success "Removed openclaw system user and home directory"
    else
        # User already gone, clean up home dir if it remains
        rm -rf /home/openclaw
        success "openclaw user not found, cleaned up /home/openclaw if present"
    fi
else
    info "Removing OpenClaw runtime config ..."
    rm -rf /home/openclaw/.openclaw
    success "Removed /home/openclaw/.openclaw/"
    warn "OpenClaw binary and user preserved (use --full to remove completely)"
fi

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
    success "WireGuard config and keys removed (--full)"
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
    echo -e "    - OpenClaw binary and system user"
    echo -e "    - APT packages"
    echo
fi
