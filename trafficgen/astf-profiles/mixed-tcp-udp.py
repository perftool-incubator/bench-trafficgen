# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python
"""
NFV Scenario: Mixed TCP + UDP (Realistic NFV Traffic)
======================================================

Purpose: Simulate a realistic NFV traffic mix with predominantly TCP (99%)
         and a small fraction of UDP (1%), matching production workload
         characteristics for OpenStack/OpenShift Telco environments.

         This profile mirrors the generate_traffic_profile() function from
         cps_ndr.py (Robin Jarry / Red Hat) which was used to benchmark
         OVS+conntrack performance.

Target KPI: Maximum combined CPS at < 0.1% connection error rate.

DUT Setup: Same as short-lived-tcp.py with both TCP and UDP timeout zones.

Recommended bench-trafficgen parameters:
    --traffic-generator=trex-astf
    --astf-protocol=mixed
    --astf-udp-percent=1.0
    --astf-max-flows=50000
    --astf-ramp-time=10
    --astf-max-error-pct=0.1

Tunables:
    --message-size   Payload size (default: 20)
    --udp-percent    UDP percentage 0-100 (default: 1)
    --max-flows      Max concurrent flows (default: 50000)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append('/opt/trex/current/automation/trex_control_plane/interactive')

from trex.astf.api import *

MULTIPLIER = 100


class Prof1():
    def get_profile(self, tunables=[], **kwargs):
        parser = argparse.ArgumentParser(description='Mixed TCP+UDP profile')
        parser.add_argument('--message-size',    type=int,   default=20)
        parser.add_argument('--udp-percent',     type=float, default=1.0)
        parser.add_argument('--max-flows',       type=int,   default=50000)
        parser.add_argument('--server-wait-ms',  type=int,   default=0)
        parser.add_argument('--tcp-port',        type=int,   default=8080)
        parser.add_argument('--udp-port',        type=int,   default=5353)
        parser.add_argument('--client-ip-start', default='16.0.0.0')
        parser.add_argument('--client-ip-end',   default='16.0.255.255')
        parser.add_argument('--server-ip-start', default='48.0.0.0')
        parser.add_argument('--server-ip-end',   default='48.0.255.255')
        parser.add_argument('--ip-offset',       default='1.0.0.0')
        args = parser.parse_args(tunables)

        udp_ratio = args.udp_percent / 100.0
        tcp_ratio = 1.0 - udp_ratio
        tcp_base  = max(1, int(MULTIPLIER * tcp_ratio))
        udp_base  = max(1, int(MULTIPLIER * udp_ratio))

        ip_gen = ASTFIPGen(
            glob=ASTFIPGenGlobal(ip_offset=args.ip_offset),
            dist_client=ASTFIPGenDist(
                ip_range=[args.client_ip_start, args.client_ip_end],
                distribution='seq'),
            dist_server=ASTFIPGenDist(
                ip_range=[args.server_ip_start, args.server_ip_end],
                distribution='seq')
        )

        sched = ASTFGlobalInfo()
        sched.scheduler.rampup_sec = 5

        templates = []
        limit_total = args.max_flows if args.max_flows > 0 else None

        # UDP template (stream=False, send_msg/recv_msg)
        if udp_base > 0:
            msg_u  = b'u' * args.message_size
            resp_u = b'U' * args.message_size
            prog_uc = ASTFProgram(stream=False)
            prog_us = ASTFProgram(stream=False)
            prog_uc.send_msg(msg_u)
            prog_us.recv_msg(1)
            if args.server_wait_ms > 0:
                prog_us.delay(args.server_wait_ms * 1000)
            prog_us.send_msg(resp_u)
            prog_uc.recv_msg(1)
            limit_u = int(limit_total * udp_base / (tcp_base + udp_base)) if limit_total else None
            templates.append(ASTFTemplate(
                client_template=ASTFTCPClientTemplate(
                    program=prog_uc, ip_gen=ip_gen,
                    port=args.udp_port, cps=udp_base,
                    limit=limit_u, cont=True),
                server_template=ASTFTCPServerTemplate(
                    program=prog_us,
                    assoc=ASTFAssociationRule(port=args.udp_port))
            ))

        # TCP template (stream=True, send/recv)
        if tcp_base > 0:
            req  = b'x' * args.message_size
            resp = b'y' * args.message_size
            prog_tc = ASTFProgram(stream=True)
            prog_ts = ASTFProgram(stream=True)
            prog_tc.send(req)
            prog_ts.recv(args.message_size)
            if args.server_wait_ms > 0:
                prog_ts.delay(args.server_wait_ms * 1000)
            prog_ts.send(resp)
            prog_tc.recv(args.message_size)
            limit_t = int(limit_total * tcp_base / (tcp_base + udp_base)) if limit_total else None
            templates.append(ASTFTemplate(
                client_template=ASTFTCPClientTemplate(
                    program=prog_tc, ip_gen=ip_gen,
                    port=args.tcp_port, cps=tcp_base,
                    limit=limit_t, cont=True),
                server_template=ASTFTCPServerTemplate(
                    program=prog_ts,
                    assoc=ASTFAssociationRule(port=args.tcp_port))
            ))

        return ASTFProfile(
            default_ip_gen=ip_gen,
            default_c_glob_info=sched,
            templates=templates
        )


def register():
    return Prof1()
