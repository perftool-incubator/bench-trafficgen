# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python
"""
NFV Scenario: Short-Lived TCP Connections
==========================================

Purpose: Stress the conntrack INSERT/DELETE code path on OVS+conntrack DUT.
         Each connection completes quickly (1 request + 1 reply, no wait),
         maximizing the rate of new conntrack entry creation and destruction.

Target KPI: Maximum CPS (connections per second) at < 0.1% connection error rate.

DUT Setup:
    ovs-appctl dpctl/ct-set-maxconns 5000000
    ovs-vsctl add-zone-tp netdev zone=0 tcp_syn_sent=1 tcp_syn_recv=1 \
        tcp_fin_wait=1 tcp_time_wait=1 tcp_close=1 tcp_established=30

Recommended bench-trafficgen parameters:
    --traffic-generator=trex-astf
    --astf-profile=<this file>
    --astf-max-flows=50000
    --astf-ramp-time=10
    --astf-max-error-pct=0.1
    --pre-trial-cmd="conntrack -F"

Tunables (pass via --astf-profile-tunables or directly in ASTF CLI):
    --message-size    Payload bytes per request/response (default: 20)
    --max-flows       Max concurrent flows (default: 50000)
    --tcp-port        Destination TCP port (default: 8080)
    --client-ip-start First client IP (default: 16.0.0.0)
    --server-ip-start First server IP (default: 48.0.0.0)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append('/opt/trex/current/automation/trex_control_plane/interactive')

from trex.astf.api import *


class Prof1():
    def get_profile(self, tunables=[], **kwargs):
        parser = argparse.ArgumentParser(description='Short-lived TCP profile')
        parser.add_argument('--message-size',    type=int, default=20)
        parser.add_argument('--max-flows',       type=int, default=50000)
        parser.add_argument('--tcp-port',        type=int, default=8080)
        parser.add_argument('--client-ip-start', default='16.0.0.0')
        parser.add_argument('--client-ip-end',   default='16.0.255.255')
        parser.add_argument('--server-ip-start', default='48.0.0.0')
        parser.add_argument('--server-ip-end',   default='48.0.255.255')
        parser.add_argument('--ip-offset',       default='1.0.0.0')
        args = parser.parse_args(tunables)

        request  = b'x' * args.message_size
        response = b'y' * args.message_size

        # TCP: one request, one response, immediate close
        prog_c = ASTFProgram(stream=True)
        prog_c.send(request)
        prog_c.recv(args.message_size)

        prog_s = ASTFProgram(stream=True)
        prog_s.recv(args.message_size)
        prog_s.send(response)

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

        limit = args.max_flows if args.max_flows > 0 else None

        return ASTFProfile(
            default_ip_gen=ip_gen,
            default_c_glob_info=sched,
            templates=ASTFTemplate(
                client_template=ASTFTCPClientTemplate(
                    program=prog_c, ip_gen=ip_gen,
                    port=args.tcp_port, cps=100,
                    limit=limit, cont=True),
                server_template=ASTFTCPServerTemplate(
                    program=prog_s,
                    assoc=ASTFAssociationRule(port=args.tcp_port))
            )
        )


def register():
    return Prof1()
