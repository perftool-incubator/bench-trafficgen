#!/bin/bash
# -*- mode: sh; indent-tabs-mode: nil; sh-basic-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=bash

# Periodic Grout stats collector — polls grcli for hardware and software
# stats at a configurable interval, producing CSV and detailed log files
# for post-test analysis.
#
# Usage: grout-stats-collector.sh --socket <path> --interval <secs> \
#            --hw-output <file> --sw-output <file>

grout_sock=""
interval=5
hw_output="trafficgen-grout-hw-stats.csv"
sw_output="trafficgen-grout-sw-stats.csv"

re='^(--[^=]+)=([^=]+)'
while [ $# -gt 0 ]; do
    if [[ "$1" =~ $re ]]; then
        arg="${BASH_REMATCH[1]}"
        val="${BASH_REMATCH[2]}"
        shift
    else
        arg="$1"
        shift
        val="$1"
        shift
    fi
    case "$arg" in
        --socket)
            grout_sock="$val"
            ;;
        --interval)
            interval="$val"
            ;;
        --hw-output)
            hw_output="$val"
            ;;
        --sw-output)
            sw_output="$val"
            ;;
    esac
done

if [ -z "${grout_sock}" ]; then
    echo "ERROR: --socket is required"
    exit 1
fi

cleanup() {
    exit 0
}
trap cleanup SIGTERM SIGINT

hw_header_written=0
sw_header_written=0

while true; do
    timestamp=$(date -u '+%Y-%m-%dT%H:%M:%S.%3NZ')
    epoch=$(date -u '+%s')

    # Hardware stats — per-port RX/TX counters
    # grcli stats show hardware outputs a table like:
    #   IFACE  RX_PACKETS  RX_BYTES  RX_ERRORS  RX_DROPS  TX_PACKETS  TX_BYTES  TX_ERRORS  TX_DROPS
    #   p0     12345       6789000   0          0         12340       6788000   0          0
    hw_raw=$(grcli -s "${grout_sock}" stats show hardware 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "${hw_raw}" ]; then
        if [ ${hw_header_written} -eq 0 ]; then
            echo "timestamp,epoch,iface,rx_packets,rx_bytes,rx_errors,rx_drops,tx_packets,tx_bytes,tx_errors,tx_drops" > "${hw_output}"
            hw_header_written=1
        fi
        echo "${hw_raw}" | tail -n +2 | while read -r line; do
            if [ -z "$line" ]; then
                continue
            fi
            iface=$(echo "$line" | awk '{print $1}')
            rx_pkts=$(echo "$line" | awk '{print $2}')
            rx_bytes=$(echo "$line" | awk '{print $3}')
            rx_errs=$(echo "$line" | awk '{print $4}')
            rx_drops=$(echo "$line" | awk '{print $5}')
            tx_pkts=$(echo "$line" | awk '{print $6}')
            tx_bytes=$(echo "$line" | awk '{print $7}')
            tx_errs=$(echo "$line" | awk '{print $8}')
            tx_drops=$(echo "$line" | awk '{print $9}')
            if [ -n "${iface}" ] && [[ "${iface}" =~ ^p[0-9] ]]; then
                echo "${timestamp},${epoch},${iface},${rx_pkts},${rx_bytes},${rx_errs},${rx_drops},${tx_pkts},${tx_bytes},${tx_errs},${tx_drops}" >> "${hw_output}"
            fi
        done
    fi

    # Software stats — per-graph-node CPU cycle counters
    # grcli stats show software outputs a table like:
    #   NODE         CALLS   PACKETS  PKTS/CALL  CYCLES/CALL  CYCLES/PKT
    #   port_rx     757792  22623757       29.9       1776.4        59.5
    sw_raw=$(grcli -s "${grout_sock}" stats show software 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "${sw_raw}" ]; then
        if [ ${sw_header_written} -eq 0 ]; then
            echo "timestamp,epoch,node,calls,packets,pkts_per_call,cycles_per_call,cycles_per_pkt" > "${sw_output}"
            sw_header_written=1
        fi
        echo "${sw_raw}" | tail -n +2 | while read -r line; do
            if [ -z "$line" ]; then
                continue
            fi
            node=$(echo "$line" | awk '{print $1}')
            calls=$(echo "$line" | awk '{print $2}')
            packets=$(echo "$line" | awk '{print $3}')
            pkts_call=$(echo "$line" | awk '{print $4}')
            cyc_call=$(echo "$line" | awk '{print $5}')
            cyc_pkt=$(echo "$line" | awk '{print $6}')
            if [ -n "${node}" ] && [[ ! "${node}" =~ ^NODE ]]; then
                echo "${timestamp},${epoch},${node},${calls},${packets},${pkts_call},${cyc_call},${cyc_pkt}" >> "${sw_output}"
            fi
        done
    fi

    sleep "${interval}"
done
