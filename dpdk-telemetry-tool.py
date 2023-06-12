#!/usr/bin/env python3

"""
Display DPDK port statistics using the telemetry socket API.
"""

import argparse
import json
import socket
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("-s",
                        "--sock-path",
                        default = "/var/run/dpdk/rte/dpdk_telemetry.v2",
                        help="""
                        Path to the DPDK telemetry UNIX socket.
                        """)

    parser.add_argument("-t",
                        "--time",
                        type = int,
                        default = 1,
                        help="""
                        Time interval between each statistics sample.
                        """)

    args = parser.parse_args()

    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        sock.connect(args.sock_path)
        data = json.loads(sock.recv(1024).decode())
        max_out_len = data["max_output_len"]

        def cmd(c):
            sock.send(c.encode())
            return json.loads(sock.recv(max_out_len))

        port_ids = cmd("/ethdev/list")["/ethdev/list"]

        def get_dev_info():
            all_info = { "devices": {} }
            for i in port_ids:
                data = cmd(f"/ethdev/info,{i}")
                all_info["devices"][i] = data["/ethdev/info"]
            return all_info
        
        def get_link_status():
            all_links = { "devices": {} }
            for i in port_ids:
                data = cmd(f"/ethdev/link_status,{i}")
                all_links["devices"][i] = data["/ethdev/link_status"]
            return all_links

        def get_stats(timestamp):
            all_stats = { "time": timestamp, "devices": {} }
            for i in port_ids:
                data = cmd(f"/ethdev/stats,{i}")
                all_stats["devices"][i] = data["/ethdev/stats"]
            return all_stats

        def get_xstats(timestamp):
            all_xstats = { "time": timestamp, "devices": {} }
            for i in port_ids:
                data = cmd(f"/ethdev/xstats,{i}")
                all_xstats["devices"][i] = data["/ethdev/xstats"]
            return all_xstats

        dev_info = get_dev_info()
        print(dev_info)
        print("---")
        link_status = get_link_status()
        print(link_status)
        
        while True:
            print("---")
            ts = time.time() * 1000.0
            stats = get_stats(ts)
            #xstats = get_xstats(ts)
            print(stats)
            #print(xstats)
            time.sleep(args.time)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        if isinstance(e, FileNotFoundError):
            e = f"{args.sock_path}: {e}"
        print(f"error: {e}")
    finally:
        if sock is not None:
            sock.close()


if __name__ == "__main__":
    main()
