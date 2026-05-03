#!/usr/bin/python3 -u
# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

"""
Query a TRex server running in ASTF mode for port information.

STLClient cannot connect to an ASTF-mode TRex server, so this script uses
ASTFClient for port queries when traffic-generator=trex-astf.

Emits PARSABLE PORT INFO on stderr in the same format as trex-query.py so
that binary-search.py's get_trex_port_info() can parse it identically.
"""

from __future__ import print_function

import sys
import argparse

sys.path.append('/opt/trex/current/automation/trex_control_plane/interactive')

from trex.astf.api import ASTFClient
from tg_lib import dump_json_parsable, dump_json_readable, error


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
        description='Query TRex (ASTF mode) for port information'
    )
    parser.add_argument('--trex-host',
                        dest='trex_host', default='localhost',
                        help='Hostname/IP of the TRex server')
    parser.add_argument('--mirrored-log',
                        dest='mirrored_log', action='store_true',
                        help='Mirror stdout to stderr')
    parser.add_argument('--device',
                        dest='device', default=[], action='append', type=int,
                        help='Device port number to query (repeatable)')
    t_global.args = parser.parse_args()
    myprint(t_global.args)


def main():
    process_options()

    if len(t_global.args.device) == 0:
        myprint(error("You must provide at least one --device to query"))
        return 1

    c = ASTFClient(server=t_global.args.trex_host)
    return_value = 1

    try:
        myprint("Establishing connection to TRex ASTF server...")
        c.connect()
        myprint("Connection established")

        # Build port info compatible with STL get_port_info() output shape
        # ASTFClient exposes get_port_attr() per port; we reconstruct the list
        port_info = []
        for port_id in t_global.args.device:
            try:
                attr = c.get_port_attr(port=port_id)
                port_entry = {
                    'index':    port_id,
                    'speed':    attr.get('speed', 0),
                    'hw_mac':   attr.get('hw_mac', ''),
                    'src_mac':  attr.get('src_mac', ''),
                    'dst_mac':  attr.get('dst_mac', ''),
                    'driver':   attr.get('driver', ''),
                    'description': attr.get('description', ''),
                    'status':   attr.get('status', ''),
                }
                port_info.append(port_entry)
                myprint("Port %d: speed=%s hw_mac=%s driver=%s" % (
                    port_id,
                    port_entry['speed'],
                    port_entry['hw_mac'],
                    port_entry['driver']))
            except Exception as e:
                myprint("WARNING: Could not get info for port %d: %s" % (port_id, e))
                port_info.append({
                    'index':  port_id,
                    'speed':  0,
                    'hw_mac': '',
                    'driver': '',
                    'error':  str(e)
                })

        myprint("READABLE PORT INFO:", stderr_only=True)
        myprint(dump_json_readable(port_info), stderr_only=True)
        myprint("PARSABLE PORT INFO: %s" % dump_json_parsable(port_info),
                stderr_only=True)

        return_value = 0

    except Exception as e:
        myprint("ERROR: %s" % str(e))

    finally:
        try:
            c.disconnect()
        except Exception:
            pass
        myprint("Connection severed")

    return return_value


if __name__ == '__main__':
    sys.exit(main())
