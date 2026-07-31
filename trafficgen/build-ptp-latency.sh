#!/bin/bash
# -*- mode: sh; indent-tabs-mode: nil; sh-basic-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=bash
#
# Build ptp-latency from source. No external dependencies beyond
# standard C library and Linux kernel headers.

SOURCE="${1:-/tmp/build/ptp-latency.c}"
OUTPUT="${2:-/usr/bin/ptp-latency}"

if [ ! -f "${SOURCE}" ]; then
    echo "ERROR: Source file not found: ${SOURCE}"
    exit 1
fi

echo "Building ptp-latency..."
echo "  Source: ${SOURCE}"
echo "  Output: ${OUTPUT}"

gcc -O2 -Wall -Wextra -o "${OUTPUT}" "${SOURCE}" -lm -lrt -lpthread

rc=$?
if [ ${rc} -ne 0 ]; then
    echo "ERROR: Build failed (rc=${rc})"
    exit ${rc}
fi

echo "Build successful: ${OUTPUT}"
