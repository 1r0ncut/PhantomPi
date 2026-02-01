#!/bin/bash

source /opt/implant/config.env

create_hotspot() {
    nmcli connection add type wifi ifname "$HOTSPOT_IFACE" con-name "$HOTSPOT_SSID" \
        autoconnect no ssid "$HOTSPOT_SSID" \
        mode ap \
        802-11-wireless.hidden "$HOTSPOT_HIDDEN" \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$HOTSPOT_PSK" \
        ipv4.method shared
}

delete_hotspot() {
    for con in $(nmcli -t -f NAME,TYPE connection show | grep ':802-11-wireless' | cut -d: -f1); do
        if [[ "$con" == berry_* ]]; then
            echo "Deleting hotspot: $con"
            nmcli connection delete "$con"
        fi
    done
}

case "$1" in
    start)
        nmcli connection up "$HOTSPOT_SSID"
        ;;
    stop)
        nmcli connection down "$HOTSPOT_SSID"
        ;;
    create)
        create_hotspot
        ;;
    update)
        echo "[*] Updating hotspot configuration..."
        delete_hotspot
        create_hotspot
        ;;
    delete)
        echo "[*] Deleting all hotspot configurations..."
        delete_hotspot
        ;;
    *)
        echo "Usage: $0 {start|stop|create|update|delete}"
        exit 1
        ;;
esac
