# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python
"""
NFV Scenario: Short-Lived UDP Connections
==========================================

Purpose: Validate UDP conntrack tracking on OVS+conntrack DUT.
         UDP conntrack uses a different state machine than TCP (new/established
         based on bidirectional traffic, not SYN/FIN handshake).

Target KPI: Maximum UDP CPS at < 0.1% packet loss.

Note: Uses ASTFProgram(stream=False) with send_msg/recv_msg for UDP datagram
      semantics. This is fundamentally different from the TCP profiles.

DUT Setup:
    ovs-vsctl add-zone-tp netdev zone=0 udp_first=1 udp_single=1 udp_multiple=30

Recommended bench-trafficgen parameters:
    --traffic-generator=trex-astf
    --astf-profile=<this file>
    --astf-max-flows=50000
    --astf-ramp-time=5
    --astf-max-error-pct=0.1
    --pre-trial-cmd="conntrack -F"
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append('/opt/trex/current/automation/trex_control_plane/interactive')

from trex.astf.api import *


class Prof1():
    def get_profile(self, tunables=[], **kwargs):
        parser = argparse.ArgumentParser(description='Short-lived UDP profile')
        parser.add_argument('--message-size',    type=int, default=64)
        parser.add_argument('--max-flows',       type=int, default=50000)
        parser.add_argument('--udp-port',        type=int, default=5353)
        parser.add_argument('--client-ip-start', default='16.0.0.0')
        parser.add_argument('--client-ip-end',   default='16.0.255.255')
        parser.add_argument('--server-ip-start', default='48.0.0.0')
        parser.add_argument('--server-ip-end',   default='48.0.255.255')
        parser.add_argument('--ip-offset',       default='1.0.0.0')
        args = parser.parse_args(tunables)

        request  = b'x' * args.message_size
        response = b'y' * args.message_size

        # UDP: stream=False, send_msg/recv_msg for datagram semantics
        prog_c = ASTFProgram(stream=False)
        prog_c.send_msg(request)
        prog_c.recv_msg(1)

        prog_s = ASTFProgram(stream=False)
        prog_s.recv_msg(1)
        prog_s.send_msg(response)

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
                    port=args.udp_port, cps=100,
                    limit=limit, cont=True),
                server_template=ASTFTCPServerTemplate(
                    program=prog_s,
                    assoc=ASTFAssociationRule(port=args.udp_port))
            )
        )


def register():
    return Prof1()
