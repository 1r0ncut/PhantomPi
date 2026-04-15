#!/bin/bash

source /opt/implant/config.env

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
RAW_HEX=$(vcgencmd get_throttled | cut -d= -f2)
VALUE=$((RAW_HEX)) 

NOW_UNDERVOLTAGE=$(( VALUE & 0x1 ))
NOW_FREQ_CAPPED=$(( VALUE & 0x2 ))
NOW_THROTTLING=$(( VALUE & 0x4 ))
HIST_UNDERVOLTAGE=$(( VALUE & 0x10000 ))
HIST_FREQ_CAPPED=$(( VALUE & 0x20000 ))
HIST_THROTTLING=$(( VALUE & 0x40000 ))

MEANING=""

if [ $NOW_UNDERVOLTAGE -ne 0 ] || [ $NOW_FREQ_CAPPED -ne 0 ] || [ $NOW_THROTTLING -ne 0 ]; then
    [ $NOW_UNDERVOLTAGE -ne 0 ] && MEANING+="Undervoltage detected; "
    [ $NOW_FREQ_CAPPED -ne 0 ] && MEANING+="Frequency capped detected; "
    [ $NOW_THROTTLING -ne 0 ] && MEANING+="Throttling active detected; "
elif [ $HIST_UNDERVOLTAGE -ne 0 ] || [ $HIST_FREQ_CAPPED -ne 0 ] || [ $HIST_THROTTLING -ne 0 ]; then
    HISTORY_EVENTS=()
    [ $HIST_UNDERVOLTAGE -ne 0 ] && HISTORY_EVENTS+=("undervoltage")
    [ $HIST_FREQ_CAPPED -ne 0 ] && HISTORY_EVENTS+=("frequency capping")
    [ $HIST_THROTTLING -ne 0 ] && HISTORY_EVENTS+=("throttling")
    LIST=$(IFS=", "; echo "${HISTORY_EVENTS[*]}")
    MEANING="No current power issues; power-related events occurred previously: $LIST."
else
    MEANING="No power issues detected."
fi

echo "$TIMESTAMP - throttled=$RAW_HEX - $MEANING" >> "$POWER_MONITOR_LOG"
