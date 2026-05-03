# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python
"""
NFV Scenario: Long-Lived TCP Connections
=========================================

Purpose: Stress the conntrack LOOKUP code path on OVS+conntrack DUT.
         Each connection stays active for ~25 seconds (500 req/resp with
         50ms server wait), maximizing concurrent connections and therefore
         conntrack table lookup operations.

Target KPI: Maximum concurrent active flows (not CPS) at stable throughput.

DUT Setup:
    ovs-appctl dpctl/ct-set-maxconns 5000000
    ovs-vsctl add-zone-tp netdev zone=0 tcp_established=60

Recommended bench-trafficgen parameters:
    --traffic-generator=trex-astf
    --astf-profile=<this file>
    --astf-max-flows=500000
    --astf-ramp-time=30
    --search-runtime=120
    --astf-max-error-pct=0.1

Tunables:
    --message-size     Payload bytes per message (default: 20)
    --num-messages     Number of req/resp pairs per connection (default: 500)
    --server-wait-ms   Server delay per response in ms (default: 50)
    --max-flows        Max concurrent flows (default: 500000)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append('/opt/trex/current/automation/trex_control_plane/interactive')

from trex.astf.api import *


class Prof1():
    def get_profile(self, tunables=[], **kwargs):
        parser = argparse.ArgumentParser(description='Long-lived TCP profile')
        parser.add_argument('--message-size',    type=int, default=20)
        parser.add_argument('--num-messages',    type=int, default=500)
        parser.add_argument('--server-wait-ms',  type=int, default=50)
        parser.add_argument('--max-flows',       type=int, default=500000)
        parser.add_argument('--tcp-port',        type=int, default=8080)
        parser.add_argument('--client-ip-start', default='16.0.0.0')
        parser.add_argument('--client-ip-end',   default='16.0.255.255')
        parser.add_argument('--server-ip-start', default='48.0.0.0')
        parser.add_argument('--server-ip-end',   default='48.0.255.255')
        parser.add_argument('--ip-offset',       default='1.0.0.0')
        args = parser.parse_args(tunables)

        request  = b'x' * args.message_size
        response = b'y' * args.message_size

        prog_c = ASTFProgram(stream=True)
        prog_s = ASTFProgram(stream=True)
        for _ in range(max(1, args.num_messages)):
            prog_c.send(request)
            prog_s.recv(args.message_size)
            if args.server_wait_ms > 0:
                prog_s.delay(args.server_wait_ms * 1000)
            prog_s.send(response)
            prog_c.recv(args.message_size)

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
        sched.scheduler.rampup_sec = 30

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
