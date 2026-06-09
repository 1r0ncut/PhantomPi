#!/bin/bash

source /opt/implant/config.env

MODEM_REBOOT_ATTEMPTS="${WG_MODEM_REBOOT_ATTEMPTS:-1}"
MODEM_REBOOT_WAIT_SECONDS="${WG_MODEM_REBOOT_WAIT_SECONDS:-60}"
MODEM_CONFIG="${MODEM_CONFIG:-/opt/implant/scripts/modem-config.sh}"
LTE_SERIAL_DEVICE="${LTE_SERIAL_DEVICE:-/dev/ttyUSB2}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] - $*" >> "$WG_KEEPALIVE_LOG"
}

ping_server() {
    ping -c "$WG_PING_ATTEMPTS" "$WG_SERVER_IP" &>/dev/null
}

log_diagnostics() {
    {
        echo
        echo "===================================================================="
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] - All WireGuard recovery stages failed. Rebooting implant..."
        echo "===================================================================="

        echo
        echo "==== Network Interface State ===="
        ip a

        echo
        echo "==== Routing Table ===="
        ip route show

        echo
        echo "==== Uptime ===="
        uptime

        echo
        echo "==== nmcli device ===="
        nmcli device

        echo
        echo "==== dmesg (tail -50) ===="
        dmesg | tail -50

        echo
        echo "==== journalctl -n 50 ===="
        journalctl -n 50 --no-pager

        if [ -f /var/log/kern.log ]; then
            echo
            echo "==== /var/log/kern.log (tail -50) ===="
            tail -50 /var/log/kern.log
        fi
    } >> "$WG_KEEPALIVE_LOG" 2>&1
}

if ! [[ "$MODEM_REBOOT_ATTEMPTS" =~ ^[0-9]+$ ]]; then
    log "Invalid WG_MODEM_REBOOT_ATTEMPTS='$MODEM_REBOOT_ATTEMPTS'; using 1."
    MODEM_REBOOT_ATTEMPTS=1
fi

if ! [[ "$MODEM_REBOOT_WAIT_SECONDS" =~ ^[0-9]+$ ]]; then
    log "Invalid WG_MODEM_REBOOT_WAIT_SECONDS='$MODEM_REBOOT_WAIT_SECONDS'; using 60."
    MODEM_REBOOT_WAIT_SECONDS=60
fi

if ping_server; then
    exit 0
fi

log "WireGuard server $WG_SERVER_IP unreachable after $WG_PING_ATTEMPTS ping attempts."

for ((attempt = 1; attempt <= MODEM_REBOOT_ATTEMPTS; attempt++)); do
    log "Recovery stage $attempt/$MODEM_REBOOT_ATTEMPTS: rebooting LTE modem via $LTE_SERIAL_DEVICE."

    if "$MODEM_CONFIG" "$LTE_SERIAL_DEVICE" reboot >> "$WG_KEEPALIVE_LOG" 2>&1; then
        log "Modem reboot command accepted. Waiting ${MODEM_REBOOT_WAIT_SECONDS}s for LTE and WireGuard recovery."
    else
        log "Modem reboot command failed. Waiting ${MODEM_REBOOT_WAIT_SECONDS}s before testing connectivity."
    fi

    sleep "$MODEM_REBOOT_WAIT_SECONDS"

    if ping_server; then
        log "WireGuard connectivity restored after modem recovery stage $attempt."
        exit 0
    fi

    log "WireGuard server still unreachable after modem recovery stage $attempt."
done

log_diagnostics
sleep 5
reboot
