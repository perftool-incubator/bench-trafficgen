#!/bin/bash
# -*- mode: sh; indent-tabs-mode: nil; sh-basic-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=bash

grout_ver="v0.16.0"
insecure_curl=0
bundled_rpm="/opt/grout/grout.x86_64.rpm"
github_base_url="https://github.com/DPDK/grout/releases/download"

opts=$(getopt -q -o "" --longoptions "version:,insecure,help" -n "install-grout.sh" -- "$@")
if [ $? -ne 0 ]; then
    echo "ERROR: invalid options"
    exit 1
fi
eval set -- "$opts"
while true; do
    case "${1}" in
        --version)
            shift
            if [ -n "${1}" ]; then
                grout_ver=${1}
                shift
            fi
            ;;
        --insecure)
            shift
            insecure_curl=1
            ;;
        --help)
            printf -- "install-grout.sh — install Grout DPDK L3 router\n"
            printf -- "\n"
            printf -- "Options:\n"
            printf -- "  --version=VERSION  Grout version to install (default: %s)\n" "${grout_ver}"
            printf -- "  --insecure         Disable SSL cert verification for download\n"
            printf -- "  --help             Show this help\n"
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            if [ -n "${1}" ]; then
                echo "ERROR: Unrecognized option ${1}"
            fi
            exit 1
            ;;
    esac
done

echo "Requested Grout version: ${grout_ver}"

dnf install -y libevent numactl-libs libmnl 2>&1
if [ $? -ne 0 ]; then
    echo "WARNING: some Grout dependencies may not have installed cleanly"
fi

# Determine whether to use the bundled RPM or download from GitHub.
# The bundled RPM avoids internet dependency at build time; downloading
# is only needed when a non-default version is requested at runtime.
use_bundled=0
if [ -f "${bundled_rpm}" ]; then
    bundled_ver=$(rpm -qp --queryformat '%{VERSION}' "${bundled_rpm}" 2>/dev/null)
    if [ "${grout_ver}" == "v${bundled_ver}" ]; then
        use_bundled=1
    fi
fi

if [ ${use_bundled} -eq 1 ]; then
    echo "Installing bundled Grout ${grout_ver} from ${bundled_rpm}"
    dnf install -y "${bundled_rpm}"
    rc=$?
else
    rpm_url="${github_base_url}/${grout_ver}/grout.x86_64.rpm"
    curl_args=""
    if [ "${insecure_curl}" == "1" ]; then
        curl_args="--insecure"
    fi
    echo "Downloading Grout ${grout_ver} from ${rpm_url}..."
    tmp_rpm="/tmp/grout-${grout_ver}.x86_64.rpm"
    curl -L ${curl_args} --silent --fail --output "${tmp_rpm}" "${rpm_url}"
    curl_rc=$?
    if [ "${curl_rc}" != "0" ]; then
        if [ "${curl_rc}" == "60" ]; then
            echo "ERROR: SSL certificate validation failed. Use --insecure if appropriate."
        else
            echo "ERROR: Grout download failed (curl return code: ${curl_rc})"
        fi
        exit 1
    fi
    echo "Installing Grout ${grout_ver} from downloaded RPM"
    dnf install -y "${tmp_rpm}"
    rc=$?
    rm -f "${tmp_rpm}"
fi

if [ ${rc} -ne 0 ]; then
    echo "ERROR: Grout RPM installation failed"
    exit 1
fi

echo "Grout installed successfully: $(grout --version 2>/dev/null || echo ${grout_ver})"
