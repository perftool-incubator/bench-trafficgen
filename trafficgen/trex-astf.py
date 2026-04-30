#!/usr/bin/python3 -u
# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

"""
TRex Advanced Stateful (ASTF) trial runner.

Connects to a TRex server running in --astf mode, executes one trial, and
emits results on stderr in the PARSABLE RESULT format expected by binary-search.py.

Usage: invoked by binary-search.py when --traffic-generator=trex-astf.
Do not call directly unless testing.

Protocol support:
  tcp   -- ASTFProgram(stream=True),  send/recv byte-stream
  udp   -- ASTFProgram(stream=False), send_msg/recv_msg datagrams
  mixed -- both TCP + UDP templates (mirrors cps_ndr.py)
"""

from __future__ import print_function

import sys
import os
import json
import time
import argparse
import datetime

sys.path.append('/opt/trex/current/automation/trex_control_plane/interactive')

from trex.astf.api import ASTFClient
from trex_astf_lib import (ASTF_MULTIPLIER, astf_null_stats,
                            build_tcp_profile, build_udp_profile, build_mixed_profile,
                            load_astf_profile_file, validate_ip_ranges,
                            wait_for_cps_stable, aggregate_flow_rtt)
from tg_lib import dump_json_parsable, dump_json_readable


class t_global(object):
    args = None


def myprint(*args, **kwargs):
    stderr_only = kwargs.pop('stderr_only', False)
    if not stderr_only:
        print(*args, **kwargs)
    if stderr_only or t_global.args.mirrored_log:
        print(*args, file=sys.stderr, **kwargs)


def process_options():
    parser = argparse.ArgumentParser(
        description='Execute one TRex ASTF trial and emit PARSABLE RESULT on stderr'
    )

    # TRex connectivity
    parser.add_argument('--trex-host',
                        dest='trex_host', default='localhost',
                        help='TRex server hostname/IP')
    parser.add_argument('--device-pairs',
                        dest='device_pairs', default='0:1',
                        help='Port pairs e.g. 0:1,2:3 (client:server per pair)')
    parser.add_argument('--active-device-pairs',
                        dest='active_device_pairs', default='',
                        help='Active port pairs (defaults to --device-pairs)')
    parser.add_argument('--mirrored-log',
                        dest='mirrored_log', action='store_true',
                        help='Mirror stdout to stderr')
    parser.add_argument('--no-promisc',
                        dest='no_promisc', action='store_true',
                        help='Disable promiscuous mode (required for SR-IOV VFs)')

    # Rate control
    parser.add_argument('--mult',
                        dest='mult', default=1.0, type=float,
                        help='CPS multiplier: actual_CPS = mult * %d' % ASTF_MULTIPLIER)
    parser.add_argument('--rate-unit',
                        dest='rate_unit', default='cps-mult',
                        choices=['cps-mult', 'cps'],
                        help='Rate unit: cps-mult (multiplier) or cps (absolute)')
    parser.add_argument('--runtime',
                        dest='runtime', default=30, type=int,
                        help='Sampling duration in seconds (after ramp-up)')
    parser.add_argument('--runtime-tolerance',
                        dest='runtime_tolerance', default=5.0, type=float,
                        help='Acceptable runtime variance percentage')

    # Protocol and traffic shape
    parser.add_argument('--astf-protocol',
                        dest='astf_protocol', default='tcp',
                        choices=['tcp', 'udp', 'mixed'],
                        help='Protocol: tcp, udp, or mixed (TCP+UDP)')
    parser.add_argument('--astf-tcp-port',
                        dest='astf_tcp_port', default=8080, type=int,
                        help='Destination port for TCP template')
    parser.add_argument('--astf-udp-port',
                        dest='astf_udp_port', default=5353, type=int,
                        help='Destination port for UDP template')
    parser.add_argument('--astf-udp-percent',
                        dest='astf_udp_percent', default=1.0, type=float,
                        help='UDP percentage in mixed mode (0.0-100.0)')
    parser.add_argument('--astf-message-size',
                        dest='astf_message_size', default=64, type=int,
                        help='Payload size in bytes per message')
    parser.add_argument('--astf-num-messages',
                        dest='astf_num_messages', default=1, type=int,
                        help='Number of request/response pairs per connection')
    parser.add_argument('--astf-server-wait-ms',
                        dest='astf_server_wait_ms', default=0, type=int,
                        help='Server response delay in milliseconds')
    parser.add_argument('--astf-tcp-mss',
                        dest='astf_tcp_mss', default=1400, type=int,
                        help='TCP Maximum Segment Size in bytes')

    # IP addressing
    parser.add_argument('--astf-client-ip-start',
                        dest='astf_client_ip_start', default='16.0.0.0',
                        help='First client IP address')
    parser.add_argument('--astf-client-ip-end',
                        dest='astf_client_ip_end', default='16.0.255.255',
                        help='Last client IP address')
    parser.add_argument('--astf-server-ip-start',
                        dest='astf_server_ip_start', default='48.0.0.0',
                        help='First server IP address')
    parser.add_argument('--astf-server-ip-end',
                        dest='astf_server_ip_end', default='48.0.255.255',
                        help='Last server IP address')
    parser.add_argument('--astf-ip-offset',
                        dest='astf_ip_offset', default='1.0.0.0',
                        help='Global IP offset for dual-port pair isolation')

    # Flow control
    parser.add_argument('--astf-max-flows',
                        dest='astf_max_flows', default=0, type=int,
                        help='Max concurrent flows per template (0=unlimited)')
    parser.add_argument('--astf-ramp-time',
                        dest='astf_ramp_time', default=5, type=int,
                        help='Seconds to wait for CPS to stabilize before sampling')

    # Layer 2/3 features
    parser.add_argument('--astf-vlan-id',
                        dest='astf_vlan_id', default=0, type=int,
                        help='VLAN ID for tagged traffic (0=no VLAN)')
    parser.add_argument('--astf-ipv6',
                        dest='astf_ipv6', action='store_true',
                        help='Enable IPv6 mode')
    parser.add_argument('--astf-ipv6-client-msb',
                        dest='astf_ipv6_client_msb', default='ff02::',
                        help='IPv6 MSB for client addresses (LSB from IPv4 range)')
    parser.add_argument('--astf-ipv6-server-msb',
                        dest='astf_ipv6_server_msb', default='ff03::',
                        help='IPv6 MSB for server addresses (LSB from IPv4 range)')

    # External profile
    parser.add_argument('--astf-profile',
                        dest='astf_profile', default='',
                        help='Path to external ASTF .py profile file (overrides built-in)')

    # ICMP latency probes alongside ASTF traffic
    parser.add_argument('--astf-latency-pps',
                        dest='astf_latency_pps', default=0, type=int,
                        help='ICMP latency probe rate in pps (0=disabled)')

    # L2 MAC configuration (required for DUT that doesn't respond to ARP, e.g. testpmd io mode)
    parser.add_argument('--dst-macs',
                        dest='dst_macs', default='',
                        help='Comma-separated destination MACs, 1 per port (from DUT)')
    parser.add_argument('--src-macs',
                        dest='src_macs', default='',
                        help='Comma-separated source MACs, 1 per port (override HW MAC)')

    t_global.args = parser.parse_args()

    # Compute actual mult value when rate-unit=cps
    if t_global.args.rate_unit == 'cps':
        t_global.args.mult = t_global.args.mult / ASTF_MULTIPLIER

    return t_global.args


def build_profile():
    """Build the ASTFProfile from arguments or external file."""
    args = t_global.args

    if args.astf_profile:
        myprint("Loading external ASTF profile from: %s" % args.astf_profile)
        return load_astf_profile_file(args.astf_profile)

    validate_ip_ranges(args.astf_client_ip_start, args.astf_client_ip_end,
                       args.astf_server_ip_start, args.astf_server_ip_end)

    common_kwargs = dict(
        message_size      = args.astf_message_size,
        num_messages      = args.astf_num_messages,
        server_wait_ms    = args.astf_server_wait_ms,
        max_flows         = args.astf_max_flows,
        client_ip_start   = args.astf_client_ip_start,
        client_ip_end     = args.astf_client_ip_end,
        server_ip_start   = args.astf_server_ip_start,
        server_ip_end     = args.astf_server_ip_end,
        ip_offset         = args.astf_ip_offset,
        rampup_sec        = args.astf_ramp_time,
        enable_ipv6       = args.astf_ipv6,
        ipv6_client_msb   = args.astf_ipv6_client_msb,
        ipv6_server_msb   = args.astf_ipv6_server_msb,
    )

    if args.astf_protocol == 'tcp':
        myprint("Building built-in TCP profile (msg=%dB, msgs=%d, wait=%dms, mss=%d)" % (
            args.astf_message_size, args.astf_num_messages,
            args.astf_server_wait_ms, args.astf_tcp_mss))
        return build_tcp_profile(
            tcp_port  = args.astf_tcp_port,
            tcp_mss   = args.astf_tcp_mss,
            **common_kwargs
        )

    elif args.astf_protocol == 'udp':
        myprint("Building built-in UDP profile (msg=%dB, msgs=%d, wait=%dms)" % (
            args.astf_message_size, args.astf_num_messages, args.astf_server_wait_ms))
        return build_udp_profile(
            udp_port = args.astf_udp_port,
            **common_kwargs
        )

    else:  # mixed
        udp_ratio  = args.astf_udp_percent / 100.0
        tcp_ratio  = 1.0 - udp_ratio
        tcp_base   = max(1, int(ASTF_MULTIPLIER * tcp_ratio))
        udp_base   = max(1, int(ASTF_MULTIPLIER * udp_ratio))
        myprint("Building mixed TCP+UDP profile (TCP=%d%%, UDP=%d%%)" % (
            int(tcp_ratio * 100), int(udp_ratio * 100)))
        return build_mixed_profile(
            tcp_cps_base = tcp_base,
            udp_cps_base = udp_base,
            tcp_port     = args.astf_tcp_port,
            udp_port     = args.astf_udp_port,
            tcp_mss      = args.astf_tcp_mss,
            **common_kwargs
        )


def run_trial():
    args = t_global.args

    profile = build_profile()

    start_time = datetime.datetime.now()
    trial_start_ms = start_time.timestamp() * 1000

    c = ASTFClient(server=args.trex_host)
    stats_result = None
    err_msg = None

    try:
        myprint("Connecting to TRex ASTF server at %s" % args.trex_host)
        c.connect()
        c.reset()

        # Parse device pairs to get all port indices
        all_ports = []
        for pair_str in args.device_pairs.split(','):
            parts = pair_str.strip().split(':')
            all_ports.extend([int(p) for p in parts])
        all_ports = sorted(set(all_ports))
        myprint("All ports: %s" % str(all_ports))

        # Set promiscuous mode (required for most setups; disable for SR-IOV VFs)
        if args.no_promisc:
            myprint("Promiscuous mode disabled (SR-IOV VF mode)")
            c.set_port_attr(ports=all_ports)
        else:
            myprint("Enabling promiscuous mode on all ports")
            c.set_port_attr(ports=all_ports, promiscuous=True)

        # Configure L2 mode with destination MACs from the DUT.
        # This is CRITICAL for ASTF: unlike STL where MACs are set per-packet,
        # ASTF's TCP stack uses port-level MAC configuration. Without set_l2_mode(),
        # TRex attempts ARP resolution via the trex_cfg.yaml default_gw, which fails
        # when the DUT (e.g. testpmd io mode) does not respond to ARP.
        if args.dst_macs:
            dst_mac_list = [m.strip() for m in args.dst_macs.split(',')]
            myprint("Configuring L2 mode with destination MACs: %s" % str(dst_mac_list))
            for i, mac in enumerate(dst_mac_list):
                if i < len(all_ports):
                    port_id = all_ports[i]
                    myprint("  Port %d → dst_mac %s" % (port_id, mac))
                    c.set_l2_mode(port=port_id, dst_mac=mac)
        else:
            myprint("WARNING: No --dst-macs provided. ASTF relies on trex_cfg.yaml "
                    "port_info for MAC resolution. If the DUT does not respond to ARP "
                    "(e.g. testpmd io mode), traffic will NOT flow.")

        myprint("Loading ASTF profile")
        c.load_profile(profile)
        c.clear_stats()

        # dump_interval enables periodic TCP flow info snapshots (RTT, CWND, etc.)
        # for get_flow_info(). Adaptive: runtime/4 clamped to [1, 5] ensures >= 4
        # dumps during any measurement window regardless of runtime or payload size.
        if args.astf_protocol in ('tcp', 'mixed'):
            dump_iv = min(5.0, max(1.0, float(args.runtime) / 4.0))
        else:
            dump_iv = 0

        myprint("Starting traffic: mult=%.2f (target CPS=%.0f, latency_pps=%d, dump_interval=%.1f)" % (
            args.mult, args.mult * ASTF_MULTIPLIER, args.astf_latency_pps, dump_iv))
        c.start(mult=args.mult, dump_interval=dump_iv)

        # Ramp-up: wait for CPS to stabilize before sampling
        wait_for_cps_stable(c, args.astf_ramp_time, log_fn=myprint)

        # Clear stats after ramp-up for clean measurement window.
        # Latency probes start AFTER this clear so the latency measurement
        # window aligns exactly with the sampling window.
        c.clear_stats()

        if args.astf_latency_pps > 0:
            myprint("Starting ICMP latency probes: %d pps (src=%s, dst=%s, dual=%s)" % (
                args.astf_latency_pps,
                args.astf_client_ip_start,
                args.astf_server_ip_start,
                args.astf_ip_offset))
            try:
                c.start_latency(
                    mult=args.astf_latency_pps,
                    src_ipv4=args.astf_client_ip_start,
                    dst_ipv4=args.astf_server_ip_start,
                    dual_ipv4=args.astf_ip_offset
                )
            except Exception as e:
                myprint("WARNING: start_latency() failed: %s (continuing without latency)" % str(e))

        myprint("Sampling for %d seconds..." % args.runtime)
        time.sleep(args.runtime)

        raw_stats = c.get_stats()

        # Sample TCP RTT from active flows via get_flow_info().
        # This queries the ASTF TCP stack's internal RTT measurements --
        # real data-path latency including DUT processing overhead.
        # Adaptive poll duration: runtime/4 clamped to [2, 5] to retrieve
        # multiple pages of paginated flow data from the TRex server.
        tcp_rtt_info = {}
        if args.astf_protocol in ('tcp', 'mixed'):
            poll_dur = min(5.0, max(2.0, float(args.runtime) / 4.0))
            try:
                myprint("Sampling TCP RTT from active flows (poll=%.1fs)..." % poll_dur)
                flow_info = c.get_flow_info(duration=poll_dur)
                tcp_rtt_info = aggregate_flow_rtt(flow_info, log_fn=myprint)
            except Exception as e:
                myprint("WARNING: get_flow_info() failed: %s" % str(e))

        # Stop latency probes before stopping traffic
        if args.astf_latency_pps > 0:
            try:
                c.stop_latency()
            except Exception:
                pass

        c.stop()

        stop_time = datetime.datetime.now()
        total_time = stop_time - start_time
        measured_runtime = total_time.total_seconds()

        # Detect ASTF error counters
        traffic_stats = raw_stats.get('traffic', {})
        err_flag = False
        err_names = {}
        try:
            err_flag, err_names = c.is_traffic_stats_error(traffic_stats)
        except Exception:
            pass

        # Build the PARSABLE RESULT payload
        trial_stop_ms = stop_time.timestamp() * 1000

        # TRex interactive API returns ASTF counters directly under 'client',
        # not nested under 'client.all' (the 'all' nesting is batch mode only).
        raw_client = traffic_stats.get('client', {}) if traffic_stats else {}
        if 'all' in raw_client and isinstance(raw_client['all'], dict):
            client_stats = raw_client['all']
        else:
            client_stats = raw_client

        # Server-side counters
        raw_server = traffic_stats.get('server', {}) if traffic_stats else {}
        if 'all' in raw_server and isinstance(raw_server['all'], dict):
            server_stats = raw_server['all']
        else:
            server_stats = raw_server

        err_section = {}
        if err_flag and err_names:
            for sect, names in err_names.items():
                for k, desc in names.items():
                    err_section[k] = desc

        global_stats = raw_stats.get('global', {})
        total_stats  = raw_stats.get('total', {})

        # Per-port stats
        port_stats_list = []
        for port_id in all_ports:
            ps = raw_stats.get(port_id, {})
            if ps:
                port_stats_list.append({
                    'port':     port_id,
                    'opackets': int(ps.get('opackets', 0)),
                    'ipackets': int(ps.get('ipackets', 0)),
                    'obytes':   int(ps.get('obytes', 0)),
                    'ibytes':   int(ps.get('ibytes', 0)),
                })

        # ICMP latency stats (from latency_pps)
        latency_stats = {}
        raw_latency = raw_stats.get('latency', {})
        if raw_latency and isinstance(raw_latency, dict):
            for lat_key, lat_val in raw_latency.items():
                if isinstance(lat_val, dict) and 'latency' in lat_val:
                    lat_data = lat_val['latency']
                    latency_stats = {
                        'average':   float(lat_data.get('average', 0.0)),
                        'total_max': float(lat_data.get('total_max', 0.0)),
                        'total_min': float(lat_data.get('total_min', 0.0) if lat_data.get('total_min') != 'N/A' else 0.0),
                        'jitter':    float(lat_data.get('jitter', 0.0)),
                    }
                    break

        # Per-template-group stats
        template_stats = {}
        try:
            tg_names = c.get_tg_names()
            if tg_names:
                tg_stats = c.get_traffic_tg_stats(tg_names)
                if tg_stats:
                    for tg_name in tg_names:
                        if tg_name in tg_stats:
                            tg_client = tg_stats[tg_name].get('client', {})
                            template_stats[tg_name] = {
                                'tcps_connattempt': int(tg_client.get('tcps_connattempt', 0)),
                                'tcps_connects':    int(tg_client.get('tcps_connects', 0)),
                                'tcps_drops':       int(tg_client.get('tcps_drops', 0)),
                                'udps_connects':    int(tg_client.get('udps_connects', 0)),
                                'udps_sndpkt':      int(tg_client.get('udps_sndpkt', 0)),
                                'udps_rcvpkt':      int(tg_client.get('udps_rcvpkt', 0)),
                            }
        except Exception:
            pass

        result = {
            'trial_start': trial_start_ms,
            'trial_stop':  trial_stop_ms,
            'global': {
                'runtime':    measured_runtime,
                'timeout':    False,
                'early_exit': False,
                'force_quit': False,
                'tx_cps':     float(global_stats.get('tx_cps',  0.0)),
                'active_flows': int(global_stats.get('active_flows', 0)),
                'tx_pps':     float(global_stats.get('tx_pps',  0.0)),
                'rx_pps':     float(global_stats.get('rx_pps',  0.0)),
                'tx_bps':     float(global_stats.get('tx_bps',  0.0)),
                'rx_bps':     float(global_stats.get('rx_bps',  0.0)),
            },
            'total': {
                'opackets': int(total_stats.get('opackets', 0)),
                'ipackets': int(total_stats.get('ipackets', 0)),
            },
            'astf': {
                'client':          client_stats,
                'server':          server_stats,
                'has_astf_errors': err_flag,
                'err':             err_section,
            },
            'latency':        latency_stats,
            'port_stats':     port_stats_list,
            'template_stats': template_stats,
            'tcp_info':       tcp_rtt_info,
        }

        stats_result = result

        # Human-readable summary
        myprint("READABLE RESULT:")
        myprint(dump_json_readable(result), stderr_only=True)

    except Exception as e:
        err_msg = "trex-astf.py exception: %s" % str(e)
        myprint("ERROR: %s" % err_msg, stderr_only=True)
        stop_time = datetime.datetime.now()
        stats_result = {
            'trial_start': trial_start_ms,
            'trial_stop':  stop_time.timestamp() * 1000,
            'global': {
                'runtime':    0.0,
                'timeout':    False,
                'early_exit': False,
                'force_quit': True,
            },
            'total': {'opackets': 0, 'ipackets': 0},
            'astf':  {'client': {}, 'has_astf_errors': True,
                      'err': {'exception': str(e)}},
        }

    finally:
        try:
            c.disconnect()
        except Exception:
            pass

        # PARSABLE RESULT must be emitted BEFORE "Connection severed".
        # binary-search.py's stderr handler exits its read loop on
        # "Connection severed" -- anything printed after is never read.
        if stats_result is not None:
            print("PARSABLE RESULT: %s" % dump_json_parsable(stats_result), file=sys.stderr)

        print("Connection severed", file=sys.stderr)

    if stats_result is not None:
        return 0 if not err_msg else 1

    return 1


def main():
    process_options()
    rc = run_trial()
    sys.exit(rc)


if __name__ == '__main__':
    main()
