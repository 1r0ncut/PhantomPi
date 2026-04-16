#!/bin/bash
# =========================================================================
# PhantomPi — Setup Entry Point
# =========================================================================
# Ensures Python 3.9+ is present, then runs the setup script.
# All arguments are forwarded.
#
# Usage:
#   sudo bash setup.sh                    # default config
#   sudo bash setup.sh --debug            # verbose output
#   sudo bash setup.sh -c my_config.json  # custom config
#   sudo bash setup.sh --help             # show all options
# =========================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SETUP_DIR="$SCRIPT_DIR/setup"
INIT_PY="$SETUP_DIR/init.py"
MIN_PY=(3 9)

# ── Helpers ───────────────────────────────────────────────────────────────
RED='\033[91m'; GREEN='\033[92m'; CYAN='\033[96m'; RESET='\033[0m'
die()  { echo -e "  ${RED}[-]${RESET} $1" >&2; exit 1; }
info() { echo -e "  ${CYAN}[*]${RESET} $1"; }
ok()   { echo -e "  ${GREEN}[+]${RESET} $1"; }

# ── Root ──────────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || die "Must run as root:  sudo bash setup.sh"

# ── Repo structure ────────────────────────────────────────────────────────
[ -f "$INIT_PY" ] || die "Cannot find $INIT_PY — run this from the implant/ directory."

# ── Python 3 ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    info "Python 3 not found — installing via apt ..."
    apt-get update -qq && apt-get install -y -qq python3 \
        || die "Failed to install python3.  Install it manually and re-run."
fi

# Version check (3.9+ required for type-hint syntax used by the modules)
PY_VER=$(python3 -c 'import sys; print(sys.version_info.major, sys.version_info.minor)')
PY_MAJ=${PY_VER%% *}
PY_MIN=${PY_VER##* }

if [ "$PY_MAJ" -lt "${MIN_PY[0]}" ] || \
   { [ "$PY_MAJ" -eq "${MIN_PY[0]}" ] && [ "$PY_MIN" -lt "${MIN_PY[1]}" ]; }; then
    die "Python ${PY_MAJ}.${PY_MIN} found, but ${MIN_PY[0]}.${MIN_PY[1]}+ is required."
fi
ok "Python ${PY_MAJ}.${PY_MIN}"

# ── Hand off to the Python setup script ───────────────────────────────────
exec python3 "$INIT_PY" "$@"
