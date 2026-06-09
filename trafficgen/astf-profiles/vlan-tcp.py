# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python
"""
NFV Scenario: VLAN-Tagged TCP (SR-IOV / OVS Tenant Isolation)
==============================================================

Purpose: Test OVS+conntrack with VLAN-tagged traffic as used in:
  - OpenShift Telco SR-IOV deployments where SriovNetwork assigns VLAN tags
  - OpenStack tenant network isolation via OVS VLAN segmentation

The VLAN tag is typically configured at the TRex YAML/port level (trex_cfg.yaml)
or via the 'vlan' option on ASTFIPGenGlobal for in-profile VLAN tagging.

Note: VLAN tagging in TRex ASTF works differently from STL mode.
      The recommended approach is to configure VLAN at the TRex server level
      (trex_cfg.yaml: use_vlan) and pass --use-vlan to launch-trex.sh or
      trafficgen-infra. This profile demonstrates the in-profile approach
      using ASTFIPGenGlobal options where available.

Recommended bench-trafficgen parameters:
    --traffic-generator=trex-astf
    --astf-profile=<this file>
    --astf-vlan-id=100
    --astf-max-flows=50000
    --astf-ramp-time=10

Tunables:
    --vlan-id        VLAN ID to embed in traffic (default: 100)
    --message-size   Payload bytes (default: 64)
    --max-flows      Max concurrent flows (default: 50000)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append('/opt/trex/current/automation/trex_control_plane/interactive')

from trex.astf.api import *


class Prof1():
    def get_profile(self, tunables=[], **kwargs):
        parser = argparse.ArgumentParser(description='VLAN TCP profile')
        parser.add_argument('--vlan-id',         type=int, default=100)
        parser.add_argument('--message-size',    type=int, default=64)
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

        prog_c = ASTFProgram(stream=True)
        prog_c.send(request)
        prog_c.recv(args.message_size)

        prog_s = ASTFProgram(stream=True)
        prog_s.recv(args.message_size)
        prog_s.send(response)

        # Enable VLAN via ASTFIPGenGlobal
        # Note: vlan=True enables the VLAN dot1q header in ASTF profile
        ip_gen = ASTFIPGen(
            glob=ASTFIPGenGlobal(ip_offset=args.ip_offset, vlan=True),
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
