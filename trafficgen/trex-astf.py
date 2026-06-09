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
                            wait_for_cps_stable, aggregate_flow_rtt,
                            configure_astf_ports, sample_astf_trial,
                            assemble_astf_result)
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
    parser.add_argument('--astf-ip-offset-server',
                        dest='astf_ip_offset_server', default='',
                        help='Server-side IP offset (default: same as --astf-ip-offset)')
    parser.add_argument('--astf-per-core-distribution',
                        dest='astf_per_core_distribution', default='seq',
                        choices=['default', 'seq'],
                        help='IP distribution across TRex DP cores: seq (exclusive subsets) or default (shared)')

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

    # Flow lifecycle timeouts
    parser.add_argument('--astf-e-duration',
                        dest='astf_e_duration', default=0, type=float,
                        help='Max seconds to wait for flow establishment (0=disabled, default TCP timeout)')
    parser.add_argument('--astf-t-duration',
                        dest='astf_t_duration', default=0, type=float,
                        help='Max seconds for graceful flow teardown after stop (0=disabled, force close)')

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
        ip_offset_server  = getattr(args, 'astf_ip_offset_server', None) or None,
        per_core_distribution = getattr(args, 'astf_per_core_distribution', 'seq'),
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

        all_ports = configure_astf_ports(c, args.device_pairs, args.dst_macs,
                                         args.no_promisc, log_fn=myprint)

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

        # ASTF traffic distribution: c.start(mult=M) applies the CPS
        # multiplier evenly across all active port pairs. Per-pair IP
        # isolation is provided by ASTFIPGenGlobal(ip_offset) in the
        # profile builders. This differs from STL where each port pair
        # has independent per-stream rate control.
        myprint("Starting traffic: mult=%.2f (target CPS=%.0f, latency_pps=%d, dump_interval=%.1f)" % (
            args.mult, args.mult * ASTF_MULTIPLIER, args.astf_latency_pps, dump_iv))
        # Do NOT pass e_duration/t_duration to c.start() -- TRex's internal timers
        # are unreliable with duration=-1 (infinite) and can prematurely stop traffic
        # (see TRex issues #1167, #680). Instead, we implement our own timeout logic:
        #   e_duration: watchdog in wait_for_cps_stable() to abort if DUT unresponsive
        #   t_duration: sleep after c.stop() for graceful FIN/ACK teardown
        # nc=True: don't block on c.stop() waiting for flows to close
        start_kwargs = {'mult': args.mult, 'dump_interval': dump_iv, 'nc': True}
        if args.astf_e_duration > 0:
            myprint("  e_duration=%ds (watchdog in ramp-up, not passed to TRex)" % args.astf_e_duration)
        if args.astf_t_duration > 0:
            myprint("  t_duration=%ds (post-stop teardown wait, not passed to TRex)" % args.astf_t_duration)
        c.start(**start_kwargs)

        # Ramp-up: wait for CPS to stabilize before sampling
        wait_for_cps_stable(c, args.astf_ramp_time, log_fn=myprint,
                            e_duration=args.astf_e_duration)

        raw_stats, tcp_rtt_info = sample_astf_trial(
            c, args.runtime, protocol=args.astf_protocol,
            latency_pps=args.astf_latency_pps,
            client_ip_start=args.astf_client_ip_start,
            server_ip_start=args.astf_server_ip_start,
            ip_offset=args.astf_ip_offset, log_fn=myprint)

        c.stop()

        # t_duration: wait after stop for graceful FIN/ACK teardown.
        # This gives existing connections time to complete TCP close handshake,
        # transitioning conntrack entries from ESTABLISHED to CLOSE state
        # (which expires quickly via zone timeout policy).
        if args.astf_t_duration > 0:
            myprint("Waiting %ds for graceful teardown (t_duration)..." % args.astf_t_duration)
            time.sleep(args.astf_t_duration)

        stop_time = datetime.datetime.now()
        measured_runtime = (stop_time - start_time).total_seconds()

        result = assemble_astf_result(c, raw_stats, all_ports, trial_start_ms,
                                      measured_runtime, tcp_rtt_info, log_fn=myprint)

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
