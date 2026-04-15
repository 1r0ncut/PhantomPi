#!/bin/bash

source /opt/implant/config.env

mkdir -p "$SNIFFER_LOG_DIR"
chown tcpdump:tcpdump "$SNIFFER_LOG_DIR"

exec tcpdump -i "$SNIFFER_INTERFACE" -w "${SNIFFER_LOG_DIR}/${SNIFFER_FILE_PREFIX}.pcap" -C "$SNIFFER_MAX_FILE_SIZE_MB" -W "$SNIFFER_MAX_TOTAL_FILES" -n -U
