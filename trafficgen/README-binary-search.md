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
    ./install-trex.sh --version=v3.08
    # TRex installed to /opt/trex/v3.08
    # Symlink: /opt/trex/current -> v3.08
    ls -l /opt/trex
    # lrwxrwxrwx 1 root root 5 ... current -> v3.08
    # drwxr-xr-x 17 ...        ... v3.08
    ```

    **Recommended version**: `v3.08` for all use cases including ASTF (stateful mode).
    `v3.08` includes Python 3.12 client support, ASTF fixes, DPDK 25.07,
    and alma9 userenv support.

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

## Hardware Latency Measurement (ptp-latency)

`ptp-latency` measures one-way latency using kernel hardware timestamps (`SO_TIMESTAMPING`) on a dedicated NIC pair, running alongside TRex during each trial. It replaces TRex's built-in software latency with nanosecond-precision HW timestamps — typically 10–30x more accurate.

### Requirements

- A dedicated NIC pair (separate from TRex) with kernel PTP hardware timestamping support
- Both NICs must remain bound to kernel drivers (not DPDK/vfio-pci)
- NICs connected through the same DUT path as TRex traffic

### Enabling

Set `--latency-device-pair` to activate ptp-latency:

```
--latency-device-pair=IFACE_A:IFACE_B
```

In a crucible run file:

```json
{ "arg": "latency-device-pair", "vals": [ "ens1f0:ens1f1" ], "role": "client" }
```

### Parameters

Parameter | Default | Description
----------|---------|------------
`--latency-device-pair` | `--` (disabled) | Kernel interface pair in the form `IFACE_A:IFACE_B`. Setting this enables ptp-latency.
`--latency-probe-rate` | `1000` | Probes per second per direction. Set to `0` for maximum rate (no sleep between probes).
`--latency-warmup-packets` | `10` | Number of warmup probes sent before measurement begins.
`--latency-packet-size` | `64` | Probe frame size in bytes. Only applies when using raw probe format (NICs supporting `HWTSTAMP_FILTER_ALL`). Errors if set on NICs that require PTP Sync fallback (fixed-size format).
`--latency-max-latency` | `5` | Probe RX timeout in milliseconds. Probes not received within this window are counted as lost.
`--latency-fwd-dst-mac` | auto | Destination MAC for forward (A→B) probes. Auto-detected from interface B by default.
`--latency-rev-dst-mac` | auto | Destination MAC for reverse (B→A) probes. Auto-detected from interface A by default. Set these when the DUT rewrites MACs (e.g., a router).

### Tuning Parameters

These control CPU pinning and scheduling for the ptp-latency process. When `cpu-partitioning` is enabled at the endpoint, crucible automatically reserves a CPU and enables all tuning — no manual configuration needed.

Parameter | Default | Description
----------|---------|------------
`--latency-cpu` | none | Pin the ptp-latency process to this CPU.
`--latency-busy-poll` | `0` (disabled) | `SO_BUSY_POLL` timeout in microseconds. Reduces RX latency jitter by busy-waiting in the kernel instead of sleeping. `50` is a good starting value.
`--latency-realtime` | `OFF` | Use `SCHED_FIFO` realtime scheduling priority.
`--latency-pin-irqs` | `OFF` | Pin NIC IRQs to the `--latency-cpu`. Requires `--latency-cpu`.

### Automatic CPU Allocation

When an endpoint has `cpu-partitioning` enabled, the system automatically:

1. Reserves the last workload CPU for ptp-latency (written to `latency-cpu.txt`)
2. Passes all remaining workload CPUs to TRex
3. Enables `--latency-cpu`, `--latency-busy-poll=50`, `--latency-realtime`, and `--latency-pin-irqs`

This can be overridden by explicitly setting `--latency-cpu` in the run file.

### NIC Compatibility

ptp-latency auto-detects the NIC's hardware timestamp filter capability:

Filter | Probe Format | NICs
-------|-------------|------
`HWTSTAMP_FILTER_ALL` | Raw Ethernet (EtherType `0x88B5`) | Mellanox (mlx5), Intel X550 (ixgbe)
`HWTSTAMP_FILTER_PTP_V2_EVENT` | PTP Sync frames (EtherType `0x88F7`) | Intel X710/XXV710 (i40e)

### Example Run File

```json
{
  "arg": "latency-device-pair", "vals": [ "ens1f0:ens1f1" ], "role": "client", "enabled": "yes"
},
{
  "arg": "latency-probe-rate", "vals": [ "0" ], "role": "client", "enabled": "yes"
}
```

With `cpu-partitioning` enabled at the endpoint, this is all that's needed — CPU pinning, busy-poll, realtime scheduling, and IRQ affinity are configured automatically.
