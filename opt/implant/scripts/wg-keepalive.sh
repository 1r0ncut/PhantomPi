#!/bin/bash

source /opt/implant/config.env

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

if ! ping -c "$WG_PING_ATTEMPTS" "$WG_SERVER_IP" &>/dev/null; then
    {
        echo
        echo "===================================================================="
        echo "[$TIMESTAMP] - WireGuard server $WG_SERVER_IP unreachable. Rebooting..."
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

    sleep 5
    reboot
fi
