# binary-search.py
A script to conduct a binary search for maximum throughput or maximum connection rate.
This script is designed to work with different traffic generator backends.  Currently it
natively supports TRex (https://trex-tgn.cisco.com/) with three implementations:

- `trex-txrx` -- stateless (STL), built-in packet templates
- `trex-txrx-profile` -- stateless (STL), JSON-defined stream profiles
- `trex-astf` -- **Advanced Stateful (ASTF)**, full TCP/UDP session simulation

For ASTF documentation see [README-trex-astf.md](README-trex-astf.md).

## Installation

1.  Download this git repository:

    ```bash
    git clone https://github.com/perftool-incubator/bench-trafficgen
    ```

2.  Install TRex (requires `--version` argument):

    ```bash
    cd bench-trafficgen/trafficgen
    ./install-trex.sh --version=v3.04
    # TRex installed to /opt/trex/v3.04
    # Symlink: /opt/trex/current -> v3.04
    ls -l /opt/trex
    # lrwxrwxrwx 1 root root 5 ... current -> v3.04
    # drwxr-xr-x 17 ...        ... v3.04
    ```

    **Recommended version**: `v3.04` for all use cases including ASTF (stateful mode).
    `v3.04` includes SACK/cubic TCP improvements (v2.96), iavf/XXV710 SR-IOV fix,
    and DPDK 23.03 with stable i40e driver support.

## Configuration

1. Allocate hugepages needed by the traffic generator (1GB page size recommended).
   Reboot after modifying grub:

   ```bash
   grubby --update-kernel=`grubby --default-kernel` \
     --args="default_hugepagesz=1G hugepagesz=1G hugepages=32"
   ```

2. Bind DPDK to network interfaces using vfio-pci:

   ```bash
   driverctl set-override 0000:18:00.0 vfio-pci
   driverctl set-override 0000:18:00.1 vfio-pci
   ```

## Running (STL Mode)

`binary-search.py` is controlled entirely by command line options. See `--help` for all options.
Minimum required options for STL mode:

```
--traffic-generator   (trex-txrx or trex-txrx-profile)
--max-loss-pct
--frame-size
```

Note that you must use two physical devices connected to a DUT or loopback.

## Running (ASTF Mode)

For stateful traffic (OVS+conntrack, NAT, firewalls):

```
--traffic-generator=trex-astf
--astf-protocol=tcp          (tcp, udp, or mixed)
--astf-max-flows=50000       (stay within DUT conntrack table limits)
--astf-ramp-time=10
--astf-max-error-pct=0.1
```

See [README-trex-astf.md](README-trex-astf.md) for complete ASTF documentation.
