# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python
"""
NFV Scenario: HTTP-Like TCP (Application-Layer Stress)
=======================================================

Purpose: Simulate HTTP-like application traffic for testing OVS+conntrack
         with real L7 data exchange. Medium-duration connections with
         meaningful payload sizes exercise conntrack inspection, NAT, and
         DPI capabilities more realistically than minimal-size profiles.

Target KPI: Maximum HTTP-like CPS + L7 application bandwidth.

Tunables:
    --message-size    Payload bytes per message (default: 512 = ~HTTP GET)
    --num-messages    Messages per connection (default: 3 = 3 req/resp pairs)
    --server-wait-ms  Server processing delay in ms (default: 5)
    --max-flows       Max concurrent flows (default: 50000)
    --tcp-mss         TCP MSS (default: 1400)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append('/opt/trex/current/automation/trex_control_plane/interactive')

from trex.astf.api import *


class Prof1():
    def get_profile(self, tunables=[], **kwargs):
        parser = argparse.ArgumentParser(description='HTTP-like TCP profile')
        parser.add_argument('--message-size',    type=int, default=512)
        parser.add_argument('--num-messages',    type=int, default=3)
        parser.add_argument('--server-wait-ms',  type=int, default=5)
        parser.add_argument('--max-flows',       type=int, default=50000)
        parser.add_argument('--tcp-port',        type=int, default=80)
        parser.add_argument('--tcp-mss',         type=int, default=1400)
        parser.add_argument('--client-ip-start', default='16.0.0.0')
        parser.add_argument('--client-ip-end',   default='16.0.255.255')
        parser.add_argument('--server-ip-start', default='48.0.0.0')
        parser.add_argument('--server-ip-end',   default='48.0.255.255')
        parser.add_argument('--ip-offset',       default='1.0.0.0')
        args = parser.parse_args(tunables)

        # HTTP-like: client sends request, server responds with content
        # Use realistic sizes: ~512B request header, ~512B response
        request  = b'GET / HTTP/1.1\r\nHost: 48.0.0.1\r\nConnection: keep-alive\r\n\r\n' + b'x' * max(0, args.message_size - 60)
        response = b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n' % args.message_size + b'y' * args.message_size
        resp_len = len(response)

        prog_c = ASTFProgram(stream=True)
        prog_s = ASTFProgram(stream=True)
        for _ in range(max(1, args.num_messages)):
            prog_c.send(request)
            prog_s.recv(len(request))
            if args.server_wait_ms > 0:
                prog_s.delay(args.server_wait_ms * 1000)
            prog_s.send(response)
            prog_c.recv(resp_len)

        ip_gen = ASTFIPGen(
            glob=ASTFIPGenGlobal(ip_offset=args.ip_offset),
            dist_client=ASTFIPGenDist(
                ip_range=[args.client_ip_start, args.client_ip_end],
                distribution='seq'),
            dist_server=ASTFIPGenDist(
                ip_range=[args.server_ip_start, args.server_ip_end],
                distribution='seq')
        )

        c_glob = ASTFGlobalInfo()
        c_glob.scheduler.rampup_sec = 10
        c_glob.tcp.mss = args.tcp_mss

        limit = args.max_flows if args.max_flows > 0 else None

        return ASTFProfile(
            default_ip_gen=ip_gen,
            default_c_glob_info=c_glob,
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
