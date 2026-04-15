#!/bin/bash

set -euo pipefail

# === CONFIGURATION ===
DEFAULT_BAUDRATE=115200
TIMEOUT=2

# === FUNCTIONS ===

print_usage() {
    echo "Usage: $0 <serial_device> <command> [args...]"
    echo
    echo "Commands:"
    echo "  check-rndis                 Check if RNDIS mode is enabled"
    echo "  set-rndis <on|off>          Enable or disable RNDIS mode"
    echo "  get-apn                     Show the currently used APN"
    echo "  set-apn <apn_name>          Set a new APN"
    echo "  reboot                      Reboot the modem"
    echo
    echo "Example:"
    echo "  $0 /dev/ttyUSB2 check-rndis"
}

send_at_command() {
    local device="$1"
    local cmd="$2"
    local response

    response=$(echo -e "$cmd\r" > "$device" && timeout "$TIMEOUT" cat "$device")
    echo "$response" | sed '/^'"$cmd"'/d' | sed '/^$/d'  # remove echoed command + blank lines
}

check_device() {
    local device="$1"
    if [[ ! -e "$device" ]]; then
        echo "[!] Error: Device $device does not exist." >&2
        exit 1
    fi
    if ! grep -q "OK" <(send_at_command "$device" "AT"); then
        echo "[!] Error: Device $device does not respond to AT commands." >&2
        exit 1
    fi
}

check_rndis() {
    local device="$1"
    local response pid

    echo "[*] Checking RNDIS mode using AT+CUSBPIDSWITCH?"
    response=$(send_at_command "$device" "AT+CUSBPIDSWITCH?")

    pid=$(echo "$response" | grep "+CUSBPIDSWITCH" | sed -E 's/.*: *([0-9]+).*/\1/')

    if [[ -z "$pid" ]]; then
        echo "[!] Failed to extract PID from response:"
        echo "$response"
        return
    fi

    case "$pid" in
        9011)
            echo "[+] RNDIS mode is ACTIVE (PID: $pid)"
            ;;
        9001)
            echo "[*] ECM mode is active (PID: $pid)"
            ;;
        9015)
            echo "[-] Modem is in default (non-RNDIS) mode (PID: $pid)"
            ;;
        *)
            echo "[?] Unknown mode detected (PID: $pid)"
            ;;
    esac
}

set_rndis() {
    local device="$1"
    local mode="$2"

    case "$mode" in
        on)
            echo "[*] Enabling RNDIS mode (PID 9011)..."
            send_at_command "$device" "AT+CUSBPIDSWITCH=9011,1,1"
            echo "[!] Mode change issued. Reconnect required for effect."
            ;;
        off)
            echo "[*] Disabling RNDIS (reverting to default PID 9001)..."
            send_at_command "$device" "AT+CUSBPIDSWITCH=9001,1,1"
            echo "[!] Mode change issued. Reconnect required for effect."
            ;;
        *)
            echo "[!] Invalid mode: $mode (use 'on' or 'off')" >&2
            exit 1
            ;;
    esac
}

get_apn() {
    local device="$1"
    response=$(send_at_command "$device" "AT+CGDCONT?")
    echo "[+] Current APN configuration:"
    echo "$response" | grep "+CGDCONT"
}

set_apn() {
    local device="$1"
    local apn="$2"
    echo "[*] Setting new APN to '$apn'..."
    send_at_command "$device" "AT+CGDCONT=1,\"IP\",\"$apn\""
    echo "[+] APN updated."
}

reboot_router() {
    local device="$1"

    echo "[*] Issuing reboot command (AT+CFUN=1,1)... Connection will be lost for a while."

    local resp
    resp=$(send_at_command "$device" "AT+CFUN=1,1" || true)

    if echo "$resp" | grep -qi "OK"; then
        return 0
    fi

    echo "[!] Failed to trigger reboot. Response: '${resp:-<no response>}'"
    return 1
}

# === MAIN ===

if [[ $# -lt 2 ]]; then
    print_usage
    exit 1
fi

SERIAL_DEVICE="$1"
COMMAND="$2"
ARG="${3:-}"

check_device "$SERIAL_DEVICE"

case "$COMMAND" in
    check-rndis)
        check_rndis "$SERIAL_DEVICE"
        ;;
    set-rndis)
        if [[ -z "$ARG" ]]; then
            echo "[!] Missing argument: on|off"
            exit 1
        fi
        set_rndis "$SERIAL_DEVICE" "$ARG"
        ;;
    get-apn)
        get_apn "$SERIAL_DEVICE"
        ;;
    set-apn)
        if [[ -z "$ARG" ]]; then
            echo "[!] Missing APN value."
            exit 1
        fi
        set_apn "$SERIAL_DEVICE" "$ARG"
        ;;
    reboot)
        reboot_router "$SERIAL_DEVICE"
        ;;
    *)
        echo "[!] Unknown command: $COMMAND"
        print_usage
        exit 1
        ;;
esac

