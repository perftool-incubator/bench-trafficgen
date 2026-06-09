# trex-astf.py -- TRex Advanced Stateful Traffic Generator

## Table of Contents

- [Overview](#overview)
  - [When to Use ASTF vs STL](#when-to-use-astf-vs-stl)
  - [TCP vs UDP in ASTF](#tcp-vs-udp-in-astf)
  - [Packet Flow Topology](#packet-flow-topology)
- [Prerequisites](#prerequisites)
  - [System Requirements](#system-requirements)
  - [DUT Requirements (OVS + conntrack)](#dut-requirements-ovs--conntrack)
- [Quick Start](#quick-start)
  - [Bare-Metal 8x25G XXV710 + OVS+conntrack](#bare-metal-8x25g-xxv710--ovsconntrack)
  - [OVS-DPDK with Conntrack (4 Port Pairs)](#ovs-dpdk-with-conntrack-4-port-pairs)
  - [OpenShift SR-IOV Pod Deployment](#openshift-sr-iov-pod-deployment)
  - [Using a Preset (NFV Scenario)](#using-a-preset-nfv-scenario)
- [Parameters Reference](#parameters-reference)
  - [Core Parameters](#core-parameters)
  - [Protocol and Traffic Shape](#protocol-and-traffic-shape)
  - [IP Addressing](#ip-addressing)
  - [Flow Control](#flow-control)
  - [Layer 2/3 Features](#layer-23-features)
  - [Pass/Fail Thresholds](#passfail-thresholds)
  - [Trial Runtime Control](#trial-runtime-control)
  - [TRex DP Core Distribution](#trex-dp-core-distribution)
  - [Error Counter Reference](#error-counter-reference---astf-ignore-errors)
  - [Flow Timeout Control](#flow-timeout-control---astf-e-duration---astf-t-duration)
  - [External Profile](#external-profile-1)
- [NFV Test Scenarios](#nfv-test-scenarios)
- [OVS+Conntrack DUT Setup Reference](#ovsconntrack-dut-setup-reference)
  - [Conntrack Table Sizing](#conntrack-table-sizing)
  - [Kernel Conntrack Timeout Tuning](#kernel-conntrack-timeout-tuning)
  - [OVS Physical Port RX Queue Tuning](#ovs-physical-port-rx-queue-tuning)
  - [OVS Zone Timeout Policy](#ovs-zone-timeout-policy)
  - [Conntrack Flush Between Trials (Smart Pre-Trial-Cmd)](#conntrack-flush-between-trials-smart-pre-trial-cmd)
- [ASTF Binary Search Flow](#astf-binary-search-flow)
- [PARSABLE RESULT Format](#parsable-result-format)
- [KPIs Reported](#kpis-reported)
- [Multi-Port-Pair Traffic Distribution](#multi-port-pair-traffic-distribution)
  - [OVS-DPDK Multi-Port-Pair Deployment](#ovs-dpdk-multi-port-pair-deployment)
  - [Per-Core IP Distribution Mode](#per-core-ip-distribution-mode)
- [In-Process Persistent Connection Mode](#in-process-persistent-connection-mode)
  - [Execution Modes Comparison](#execution-modes-comparison)
  - [Conntrack-Sensitive DUTs and astf-flush-on-pass](#conntrack-sensitive-duts-and-astf-flush-on-pass)
  - [False-Positive Collapse Auto-Recovery](#false-positive-collapse-auto-recovery)
  - [Validation Trial Clean-State Guarantee](#validation-trial-clean-state-guarantee)
  - [OVS-DPDK Performance Results](#ovs-dpdk-performance-results)
  - [Trial Duration Breakdown](#trial-duration-breakdown)
  - [Reading the Logs](#reading-the-logs)
- [Troubleshooting](#troubleshooting)
  - [Roadblock Heartbeat Timeout (RC=5)](#roadblock-heartbeat-timeout-rc5)
  - [Connection Error Rate Too High](#connection-error-rate-too-high)
  - [TRex Fails to Start in ASTF Mode](#trex-fails-to-start-in-astf-mode)
  - [CPS Not Stabilizing (Ramp-Up Issues)](#cps-not-stabilizing-ramp-up-issues)
  - [SR-IOV VF Issues](#sr-iov-vf-issues)
  - [Zero Connections (Phase 1 Abort)](#zero-connections-phase-1-abort)
  - [OVS-DPDK: No Traffic Reaching VM](#ovs-dpdk-no-traffic-reaching-vm)
  - [OVS-DPDK: Phase 2 Catastrophic Errors](#ovs-dpdk-phase-2-catastrophic-errors)
  - [OVS-DPDK: Kernel Conntrack Tuning](#ovs-dpdk-kernel-conntrack-tuning)
- [External ASTF Profile Format](#external-astf-profile-format)
- [See Also](#see-also)

## Overview

`trex-astf.py` is the **Advanced Stateful (ASTF)** traffic generator backend for `binary-search.py`.
Where `trex-txrx.py` sends raw packet streams (stateless, L2/L3), `trex-astf.py` simulates full
**TCP/UDP client-server sessions** with real handshakes, data exchange, and teardown.

### When to Use ASTF vs STL

| Use Case | Recommended Backend |
|----------|-------------------|
| Maximum packet forwarding rate (RFC 2544) | `trex-txrx` or `trex-txrx-profile` |
| OVS + conntrack performance validation | **`trex-astf`** |
| NAT, stateful firewall, load balancer testing | **`trex-astf`** |
| DPI, IDS/IPS inspection testing | **`trex-astf`** |
| OpenShift SR-IOV DPDK performance validation | **`trex-astf`** |
| Connection-rate capacity planning | **`trex-astf`** |

### TCP vs UDP in ASTF

ASTF uses **different Python APIs** for TCP and UDP:

```
TCP (stream=True):  ASTFProgram uses send()/recv()     -- byte-stream, guaranteed delivery
UDP (stream=False): ASTFProgram uses send_msg()/recv_msg() -- datagram, best-effort
```

The `--astf-protocol` flag selects the mode. Use `mixed` for a combined TCP+UDP profile
(mirrors the methodology from [cps_ndr.py](https://github.com/cisco-system-traffic-generator/trex-core/blob/master/scripts/cps_ndr.py)).

### Packet Flow Topology

Unlike stateless (STL) mode where TRex sends raw packets from one port and
expects them back on another, ASTF mode runs a **full TCP/UDP stack inside
TRex itself**. TRex acts as both client and server simultaneously -- the
client side initiates connections, packets traverse the DUT, and the server
side (on the paired port) completes the handshake and data exchange.

**Topology 1: Single Port Pair (Bare-Metal, Direct Cable)**

The simplest deployment connects one TRex dual-port NIC directly to the DUT:

```
  TRex Host                                          DUT Host
  ════════                                          ════════
  ┌─────────────────────┐                       ┌──────────────────────┐
  │  TRex ASTF Engine   │                       │  testpmd / L3 fwd    │
  │  (client + server)  │                       │                      │
  │                     │                       │                      │
  │  Port 0 (client) ───┼── cable ─────────────►┼── NIC 0 (rx)         │
  │   src: 16.0.x.x     │   SYN, DATA ──►       │    │                 │
  │   dst: 48.0.x.x     │                       │    ▼   forward       │
  │                     │                       │    │   (swap MAC)    │
  │  Port 1 (server) ◄──┼── cable ◄─────────────┼── NIC 1 (tx)         │
  │   SYN-ACK, DATA ◄── │   ◄── response        │                      │
  └─────────────────────┘                       └──────────────────────┘

  Packet lifecycle (1 short-lived TCP connection):
    1. Port 0 → SYN         (16.0.0.1:ephemeral → 48.0.0.1:8080)
    2. Port 1 ← SYN-ACK     (48.0.0.1:8080 → 16.0.0.1:ephemeral)
    3. Port 0 → ACK + DATA  (64B payload)
    4. Port 1 ← DATA + ACK  (64B response)
    5. Port 0 → FIN
    6. Port 1 ← FIN-ACK
```

In this topology, `--dst-macs` is set to the DUT NIC MACs so TRex can
send directly without ARP. If the DUT is testpmd in `io` or `mac` forward
mode, `--testpmd-dst-macs` configures the return-path MACs.

**Topology 2: Single Port Pair (OVS-DPDK + VM testpmd mac-forward)**

For OVS conntrack testing, traffic passes through an OVS-DPDK bridge with
conntrack rules before reaching a VM:

```
  TRex Host                 OVS-DPDK Compute Host                    VM
  ════════                 ═════════════════════                   ═══
  ┌───────────────┐    ┌──────────────────────────────────┐    ┌───────────────┐
  │ TRex ASTF     │    │          br-int (OVS bridge)     │    │  testpmd      │
  │               │    │                                  │    │  mac-forward  │
  │ Port 0 ───────┼───►┼─ dpdk-p0 ─► ct(zone=0,commit) ──►┼───►┼─ Virtio 0     │
  │  (client tx)  │    │              conntrack INSERT    │    │    │          │
  │  dst-mac:     │    │                                  │    │    ▼ swap MAC │
  │  =Virtio0 MAC │    │                                  │    │    │          │
  │               │    │                                  │    │               │
  │ Port 1 ◄──────┼────┼─ dpdk-p1 ◄─ ct(zone=0) ◄────────┼────┼─ Virtio 1      │
  │  (server rx)  │    │              conntrack LOOKUP    │    │  (tx back)    │
  │               │    │                                  │    │               │
  └───────────────┘    └──────────────────────────────────┘    └───────────────┘

  Conntrack lifecycle:
    SYN  (Port 0 → dpdk-p0):  ct(zone=0) creates NEW entry, commit → ESTABLISHED
    DATA (Port 0 → dpdk-p0):  ct(zone=0) matches ESTABLISHED → forward
    ACK  (Virtio 1 → dpdk-p1): ct(zone=0) matches ESTABLISHED → forward to Port 1
    FIN  (either direction):   ct(zone=0) transitions to TIME_WAIT → expires (1s)
```

Note: testpmd `mac` forward mode sends return traffic through the paired
virtio port (Virtio 1), which OVS delivers to dpdk-p1 and then to TRex
Port 1. Because the return arrives on the paired port rather than the
originating port, TRex reports `err_cwf` (client packet without flow).
This is expected -- use `--astf-ignore-errors=err_cwf` to prevent hard-fail.

**Topology 3: Multi Port Pair (4 pairs, OVS-DPDK + VM testpmd mac-forward)**

For high-CPS testing, multiple port pairs distribute traffic across NICs
and PMD threads. Each pair gets an isolated IP range via `--astf-ip-offset`:

```
  TRex Host (4 NICs, 8 ports)           OVS-DPDK Compute           VM (8 virtio)
  ══════════════════════════           ════════════════           ══════════════

  Pair 0 ─ Port 0 (16.0.x.x) ────►  dpdk-p0 ──► ct ──► vhost ──► Virtio 0
            Port 1              ◄────  dpdk-p1 ◄── ct ◄── vhost ◄── Virtio 1
                                        (48.0.x.x)

  Pair 1 ─ Port 2 (17.0.x.x) ────►  dpdk-p2 ──► ct ──► vhost ──► Virtio 2
            Port 3              ◄────  dpdk-p3 ◄── ct ◄── vhost ◄── Virtio 3
                                        (49.0.x.x)

  Pair 2 ─ Port 4 (18.0.x.x) ────►  dpdk-p4 ──► ct ──► vhost ──► Virtio 4
            Port 5              ◄────  dpdk-p5 ◄── ct ◄── vhost ◄── Virtio 5
                                        (50.0.x.x)

  Pair 3 ─ Port 6 (19.0.x.x) ────►  dpdk-p6 ──► ct ──► vhost ──► Virtio 6
            Port 7              ◄────  dpdk-p7 ◄── ct ◄── vhost ◄── Virtio 7
                                        (51.0.x.x)

  IP isolation (--astf-ip-offset=1.0.0.0):
    Pair 0:  client 16.0.0.0/16  ↔  server 48.0.0.0/16
    Pair 1:  client 17.0.0.0/16  ↔  server 49.0.0.0/16   (offset +1.0.0.0)
    Pair 2:  client 18.0.0.0/16  ↔  server 50.0.0.0/16   (offset +2.0.0.0)
    Pair 3:  client 19.0.0.0/16  ↔  server 51.0.0.0/16   (offset +3.0.0.0)

  CPS distribution:
    c.start(mult=M) applies M evenly across all 4 pairs.
    Total CPS = reported CPS.  Per-pair CPS ≈ Total / 4.
```

Each pair maintains its own conntrack entries in the DUT. The IP offset
prevents cross-pair 5-tuple collisions so OVS conntrack correctly tracks
each flow independently. With `--astf-per-core-distribution=seq`, TRex
further partitions IPs within each pair across DP cores to eliminate
cross-core contention.

**MAC configuration required for multi-port OVS-DPDK:**

| Parameter | Side | Contains |
|-----------|------|----------|
| `--dst-macs` | client | VM Virtio MACs (8 MACs, one per TRex port) |
| `--testpmd-dst-macs` | server | TRex physical port MACs (8 MACs, for `--eth-peer`) |
| `--testpmd-forward-mode` | server | `mac` (enables `--eth-peer` MAC swap in testpmd) |

## Prerequisites

### System Requirements

1. **TRex with ASTF support** -- the image-installed TRex version must support ASTF mode.
   TRex v3.08 (the current default) includes SACK, cubic/newreno TCP congestion control,
   XXV710 i40e/iavf SR-IOV fixes, Python 3.12 client support, and DPDK 25.07.

2. **TRex started in `--astf` mode** -- handled automatically by `trafficgen-infra` when
   `--traffic-generator=trex-astf` is specified. STL and ASTF modes are mutually exclusive.

3. **Hugepages** -- 1G pages recommended:
   ```bash
   grubby --update-kernel=`grubby --default-kernel` --args="default_hugepagesz=1G hugepagesz=1G hugepages=32"
   ```

4. **CPU isolation** -- TRex requires isolated CPUs for line-rate performance:
   ```bash
   # Pass to trafficgen-infra
   --trex-cpus=1-11,13-23
   ```

5. **NIC bound to VFIO-DPDK**:
   ```bash
   driverctl set-override 0000:18:00.0 vfio-pci
   driverctl set-override 0000:18:00.1 vfio-pci
   ```

6. **For SR-IOV VFs** (OpenShift Telco): add `--no-promisc=ON`

### DUT Requirements (OVS + conntrack)

Configure the OVS-DPDK compute host before running tests.

**Step 1: Increase conntrack table size**

```bash
# OVS datapath conntrack limit (default may be too small for high CPS)
ovs-appctl dpctl/ct-set-maxconns 50000000

# Kernel conntrack limit -- set higher than OVS limit to avoid kernel-side
# exhaustion for management connections (SSH, Redis heartbeats, monitoring)
sysctl -w net.netfilter.nf_conntrack_max=50000000
```

Note: OVS-DPDK datapath conntrack (`dpctl/ct-set-maxconns`) and kernel
conntrack (`nf_conntrack_max`) are independent tables. OVS-DPDK data-plane
traffic uses the OVS userspace conntrack table. The kernel conntrack table
tracks only host-level connections (SSH, Redis, monitoring). Setting the
kernel limit higher avoids exhaustion from management traffic during
high-CPS test runs with /16 IP ranges.

**Step 2: Configure zone timeout policy**

```bash
ovs-vsctl add-zone-tp netdev zone=0 \
    tcp_syn_sent=1 tcp_syn_recv=1 tcp_established=30 \
    tcp_fin_wait=1 tcp_time_wait=1 tcp_close=1 \
    udp_first=1 udp_single=1 udp_multiple=30
```

**Step 3: Tune kernel conntrack timeouts**

```bash
# Infrastructure timeout -- controls how long kernel tracks established TCP
# connections (SSH, Redis heartbeats). Do NOT set below 120s; see warning below.
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=120

# Short timeouts for transient states (safe to keep aggressive)
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=1
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_fin_wait=1
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_close_wait=1
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_syn_sent=1
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_syn_recv=1
```

**WARNING**: If the compute host uses nftables with `INPUT policy drop`,
setting `nf_conntrack_tcp_timeout_established` too low (e.g., 30s) will
cause infrastructure failures. During a 60-second ASTF trial, the kernel
conntrack entry for idle TCP connections (Crucible's Redis-based roadblock
heartbeats, SSH sessions) can expire. Once expired, nftables drops the
return packets as "new" connections that don't match any INPUT rule,
causing roadblock heartbeat timeouts (RC=5) and test failures. The 120s
value provides sufficient margin for trials up to 90 seconds. This does
NOT affect OVS data-plane conntrack, which uses its own zone timeout
policy (30s established) set in Step 2.

**Step 4: Configure physical port RX queues (OVS-DPDK)**

```bash
# Set 4 RX queues per physical DPDK port to distribute traffic across PMD threads
ovs-vsctl set Interface dpdk-p0 options:n_rxq=4
ovs-vsctl set Interface dpdk-p1 options:n_rxq=4
# Repeat for all physical DPDK ports
```

With a single RX queue (default), one PMD thread handles all traffic for a
physical port and can become a bottleneck at 50%+ utilization. With `n_rxq=4`,
RSS distributes traffic across 4 queues, each handled by a separate PMD thread,
reducing per-thread utilization to ~20% at the same load. Verify with:

```bash
ovs-appctl dpif-netdev/pmd-rxq-show
```

**Step 5: Validate the configuration**

```bash
# Verify OVS conntrack max
ovs-appctl dpctl/ct-get-maxconns
# Expected: 50000000

# Verify current conntrack usage
ovs-appctl dpctl/ct-get-nconns
# Expected: low number when idle

# Verify zone timeout policy
ovs-vsctl list ct_timeout_policy
# Expected: timeouts = {tcp_close=1, tcp_established=30, tcp_fin_wait=1, ...}

# Verify kernel conntrack timeouts
sysctl net.netfilter.nf_conntrack_tcp_timeout_established
# Expected: 120

sysctl net.netfilter.nf_conntrack_max
# Expected: 50000000

# Verify RX queue configuration
ovs-vsctl get Interface dpdk-p0 options:n_rxq
# Expected: "4"
```

Note: On OpenStack compute nodes with OVN, conntrack flow rules are managed
automatically by `ovn-controller`. Do NOT manually add `ovs-ofctl` flows to
`br-int` -- this conflicts with OVN's OpenFlow pipeline. The zone timeout
policy, conntrack table sizing, and RX queue tuning above are the only manual
configuration required.

## Quick Start

### Bare-Metal 8x25G XXV710 + OVS+conntrack

Save the following as `astf-run.json` and run with `crucible run astf-run.json`:

```json
{
  "benchmarks": [
    {
      "benchmark": "trafficgen",
      "params": {
        "traffic-generator": "trex-astf",
        "astf-protocol": "tcp",
        "astf-num-messages": 1,
        "astf-message-size": 20,
        "astf-max-flows": 50000,
        "astf-ramp-time": 10,
        "astf-max-error-pct": 0.1,
        "search-runtime": 30,
        "validation-runtime": 60
      }
    }
  ],
  "endpoints": [
    {
      "type": "remotehost",
      "host": "my-trex-host",
      "client": 1,
      "config": {
        "trex-devices": "0000:18:00.0,0000:18:00.1,0000:18:02.0,0000:18:02.1"
      }
    }
  ]
}
```

Device pairs are automatically mapped: `trex-devices=0,1,2,3,4,5,6,7` maps to `device-pairs=0:1,2:3,4:5,6:7`

### OpenShift SR-IOV Pod Deployment

PCI addresses are injected as environment variables by the SR-IOV Network Operator:

```json
{
  "benchmarks": [
    {
      "benchmark": "trafficgen",
      "params": {
        "traffic-generator": "trex-astf",
        "no-promisc": "ON",
        "trex-software-mode": "on",
        "astf-protocol": "tcp",
        "astf-max-flows": 50000,
        "astf-ramp-time": 10,
        "astf-max-error-pct": 0.1
      }
    }
  ],
  "endpoints": [
    {
      "type": "k8s",
      "config": {
        "trex-devices": "VAR:PCIDEVICE_OPENSHIFT_IO_DPDK_NIC_1,VAR:PCIDEVICE_OPENSHIFT_IO_DPDK_NIC_2"
      }
    }
  ]
}
```

### Using a Preset (NFV Scenario)

Use a preset to select a pre-configured NFV scenario:

```json
{
  "benchmarks": [
    {
      "benchmark": "trafficgen",
      "params": {
        "preset": "astf_short_lived_tcp"
      }
    }
  ]
}
```

Available presets: `astf_short_lived_tcp`, `astf_long_lived_tcp`, `astf_mixed_nfv`

### OVS-DPDK with Conntrack (4 Port Pairs)

Complete profile for OVS-DPDK with a VM running testpmd in mac-forward mode.
Replace all `<placeholder>` values with your environment-specific details.

```json
{
    "benchmarks": [
        {
            "name": "trafficgen",
            "ids": "1-2",
            "mv-params": {
                "global-options": [
                    {
                        "name": "global",
                        "params": [
                            { "arg": "switch-type", "vals": ["testpmd"], "role": "server", "id": "1" },
                            { "arg": "testpmd-forward-mode", "vals": ["mac"], "role": "server" },
                            { "arg": "testpmd-queues", "vals": ["1"], "role": "server" },
                            { "arg": "testpmd-queues-per-pmd", "vals": ["1"], "role": "server" },
                            { "arg": "testpmd-smt", "vals": ["on"], "role": "server" },
                            { "arg": "testpmd-mtu", "vals": ["9216"], "role": "server" },
                            { "arg": "testpmd-descriptors", "vals": ["1024"], "role": "server" },
                            { "arg": "testpmd-dst-macs", "vals": ["<trex-port0-mac>,...,<trex-port7-mac>"], "role": "server" },
                            { "arg": "server-devices", "vals": ["<vm-pci-0>,...,<vm-pci-7>"], "role": "server" }
                        ]
                    }
                ],
                "sets": [
                    {
                        "include": "global",
                        "params": [
                            { "arg": "traffic-generator", "vals": ["trex-astf"], "role": "client" },
                            { "arg": "trex-devices", "vals": ["<trex-pci-0>,<trex-pci-1>,...,<trex-pci-7>"], "role": "client" },
                            { "arg": "dst-macs", "vals": ["<vm-virtio0-mac>,...,<vm-virtio7-mac>"], "role": "client" },
                            { "arg": "trex-mem-limit", "vals": ["32768"], "role": "client" },
                            { "arg": "astf-protocol", "vals": ["tcp"], "role": "client" },
                            { "arg": "astf-message-size", "vals": ["64"], "role": "client" },
                            { "arg": "astf-num-messages", "vals": ["1"], "role": "client" },
                            { "arg": "astf-client-ip-start", "vals": ["16.0.0.0"], "role": "client" },
                            { "arg": "astf-client-ip-end", "vals": ["16.0.255.255"], "role": "client" },
                            { "arg": "astf-server-ip-start", "vals": ["48.0.0.0"], "role": "client" },
                            { "arg": "astf-server-ip-end", "vals": ["48.0.255.255"], "role": "client" },
                            { "arg": "astf-ip-offset", "vals": ["1.0.0.0"], "role": "client" },
                            { "arg": "astf-max-flows", "vals": ["1000000"], "role": "client" },
                            { "arg": "astf-ramp-time", "vals": ["10"], "role": "client" },
                            { "arg": "astf-max-error-pct", "vals": ["5.0"], "role": "client" },
                            { "arg": "astf-max-retransmit-pct", "vals": ["20.0"], "role": "client" },
                            { "arg": "rate-unit", "vals": ["cps"], "role": "client" },
                            { "arg": "rate", "vals": ["500000"], "role": "client" },
                            { "arg": "astf-latency-pps", "vals": ["1000"], "role": "client" },
                            { "arg": "uniform-trial-runtime", "vals": ["60"], "role": "client" },
                            { "arg": "search-granularity", "vals": ["0.1"], "role": "client" },
                            { "arg": "astf-ignore-errors", "vals": ["err_cwf"], "role": "client" },
                            { "arg": "pre-trial-cmd", "vals": ["<path-to-flush-script>"], "role": "client" },
                            { "arg": "astf-per-core-distribution", "vals": ["seq"], "role": "client" },
                            { "arg": "astf-t-duration", "vals": ["10"], "role": "client" },
                            { "arg": "astf-flush-on-pass", "vals": ["ON"], "role": "client" }
                        ]
                    }
                ]
            }
        }
    ],
    "endpoints": [
        {
            "type": "remotehosts",
            "remotes": [
                {
                    "engines": [ { "role": "client", "ids": "1" } ],
                    "config": {
                        "settings": {
                            "osruntime": "chroot",
                            "host-mounts": [{ "src": "/root", "dest": "/root" }]
                        },
                        "host": "<trex-client-host>"
                    }
                },
                {
                    "engines": [ { "role": "server", "ids": "2" } ],
                    "config": {
                        "settings": { "osruntime": "chroot" },
                        "host": "<vm-server-ip>"
                    }
                }
            ]
        }
    ],
    "tags": {
        "scenario": "ovsdpdk-astf-short-lived-tcp",
        "protocol": "tcp",
        "dut": "ovs-dpdk-vm-testpmd-mac",
        "topology": "4-port-pair"
    },
    "tool-params": [
        { "tool": "sysstat" },
        { "tool": "procstat" },
        { "tool": "ovs", "params": [ { "arg": "interval", "val": "10" } ] }
    ]
}
```

**Key parameters explained:**

| Parameter | Value | Why |
|-----------|-------|-----|
| `astf-flush-on-pass` | ON | Per-trial conntrack isolation; stops traffic after every pass for clean flush |
| `astf-t-duration` | 10 | Teardown wait for TCP FIN/RST to reach OVS before conntrack flush |
| `uniform-trial-runtime` | 60 | Same duration for search and validation; prevents conntrack-related oscillation |
| `search-granularity` | 0.1 | Fine-grained convergence finds higher NDR than coarse granularity |
| `astf-per-core-distribution` | seq | Exclusive IP subsets per DP core; reduces retransmits and improves convergence |
| `astf-ignore-errors` | err_cwf | Expected in testpmd mac-fwd topology; connections still complete at 0% error |
| `pre-trial-cmd` | flush script | Conntrack flush; with flush-on-pass=ON, runs after every trial |
| `host-mounts` | /root:/root | Exposes SSH keys and flush script to the chroot container |
| `astf-max-error-pct` | 5.0 | Relaxed threshold for OVS-DPDK (more errors than bare-metal) |
| `astf-max-retransmit-pct` | 20.0 | Allows retransmit noise from OVS conntrack under sustained CPS load |

## Parameters Reference

### Core Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--traffic-generator` | `trex-txrx` | Set to `trex-astf` to enable ASTF mode |
| `--rate` | 100.0 | CPS multiplier start rate (actual CPS = rate × 100) |
| `--rate-unit` | `%` | Use `cps-mult` for multiplier or `cps` for absolute CPS |
| `--search-runtime` | 30 | Trial duration in seconds (after ramp-up) |
| `--validation-runtime` | 30 | Final validation trial duration |

### Protocol and Traffic Shape

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--astf-protocol` | `tcp` | Protocol: `tcp`, `udp`, or `mixed` |
| `--astf-message-size` | 64 | Payload bytes per request/response |
| `--astf-num-messages` | 1 | Request/response pairs per connection |
| `--astf-server-wait-ms` | 0 | Server delay before responding (ms) |
| `--astf-tcp-mss` | 1400 | TCP Maximum Segment Size (bytes) |
| `--astf-tcp-port` | 8080 | TCP destination port |
| `--astf-udp-port` | 5353 | UDP destination port |
| `--astf-udp-percent` | 1.0 | UDP % in mixed mode (0-100) |

**Frame size is implicit**: ASTF does not have an explicit `--frame-size` like STL.
Approximate frame size = `message_size` + TCP/IP/Ethernet headers (~54 bytes minimum).
For specific sizes: `--astf-message-size=20` → ~74B frames, `--astf-message-size=1440` → ~1500B frames.

### IP Addressing

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--astf-client-ip-start` | `16.0.0.0` | First client IP (SYN source) |
| `--astf-client-ip-end` | `16.0.255.255` | Last client IP |
| `--astf-server-ip-start` | `48.0.0.0` | First server IP (SYN destination) |
| `--astf-server-ip-end` | `48.0.255.255` | Last server IP |
| `--astf-ip-offset` | `1.0.0.0` | IP offset for multi-port-pair isolation |

**Multi-port-pair isolation**: For 4 dual-port pairs on 8x25G, IP ranges are auto-computed
per pair to avoid overlap:
- Pair 0:1 → client `16.0.x.x`, server `48.0.x.x`
- Pair 2:3 → client `16.1.x.x`, server `48.1.x.x`
- Pair 4:5 → client `16.2.x.x`, server `48.2.x.x`
- Pair 6:7 → client `16.3.x.x`, server `48.3.x.x`

### Flow Control

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--astf-max-flows` | 0 | Max concurrent flows (0 = unlimited) |
| `--astf-ramp-time` | 5 | Ramp-up stabilization seconds |

**conntrack table sizing**:
```
recommended_max_flows = nf_conntrack_max × 0.75
```
With default 65536 conntrack table: use `--astf-max-flows=50000`.
With 5M conntrack table: use `--astf-max-flows=3750000`.

### Layer 2/3 Features

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--astf-vlan-id` | 0 | VLAN ID (0 = no VLAN) |
| `--astf-ipv6` | `OFF` | Enable IPv6 mode |
| `--astf-ipv6-client-msb` | `ff02::` | IPv6 MSB for clients (LSB from IPv4 range) |
| `--astf-ipv6-server-msb` | `ff03::` | IPv6 MSB for servers |

### Pass/Fail Thresholds

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--astf-max-error-pct` | 0.1 | Max connection error % (primary criterion) |
| `--astf-max-retransmit-pct` | 0.0 | Max TCP retransmit % (0 = disabled) |
| `--astf-max-latency-us` | 0 | Max SYN-ACK latency μs (0 = disabled) |
| `--astf-ignore-errors` | (none) | Comma-separated ASTF error counters to treat as non-critical in Phase 2 (see "Error Counter Reference" below) |
| `--astf-e-duration` | 0 | Max seconds for flow establishment (0=disabled). Flows not established within this time are abandoned. Prevents SYN retransmit loops when DUT is unresponsive. |
| `--astf-t-duration` | 0 | Max seconds for graceful teardown after trial (0=disabled). TRex waits for FIN/ACK instead of force-killing flows. Reduces stale conntrack entries. |

### Trial Runtime Control

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--uniform-trial-runtime` | 0 | Use the same measurement duration for both search and validation trials (seconds). When set to a non-zero value, overrides both `--search-runtime` and `--validation-runtime` with this single value. |

When `--uniform-trial-runtime` is 0 (default), search and validation trials
may use different durations (controlled by `--search-runtime` and
`--validation-runtime` independently). For conntrack DUT scenarios, duration
asymmetry between search and validation can cause convergence oscillation --
a rate that passes a short search trial may fail a longer validation trial
due to conntrack table growth over time. Setting `--uniform-trial-runtime=60`
ensures consistent behavior across all trial types.

```json
{ "arg": "uniform-trial-runtime", "vals": ["60"], "role": "client" }
```

### Execution Mode

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--astf-flush-on-pass` | OFF | Stop traffic and flush conntrack after passing trials. **Recommended for all conntrack-sensitive DUTs** (OVS-DPDK, stateful firewalls, NAT). Provides per-trial isolation at the cost of ~10-20s ramp-up per trial. |
| `--astf-use-subprocess` | OFF | **Deprecated for performance evaluation.** Forces legacy subprocess-per-trial model. Retained only for debugging and A/B comparison. Not recommended for production CPS measurement. |
| `--astf-t-duration` | 0 | Seconds to wait after `client.stop()` for graceful TCP teardown. Critical for conntrack drain when `--astf-flush-on-pass=ON` or before validation trials. **Recommended: 10** for TCP, **5** for UDP. |
| `--astf-max-cps-deviation-pct` | 50 | Fails trial if actual CPS is less than (100-N)% of target. Catches flow table saturation and DUT collapse where CPS drops far below target with no error signal. Set 0 to disable. |
| `--astf-max-udp-drop-pct` | 0 | Separate UDP packet drop threshold for Phase 5 evaluation. Default 0 means use `--astf-max-error-pct`. **Recommended: 20** for mixed-mode profiles with small UDP percentage to avoid penalizing minority traffic. |

> **Production Recommendation**: Use in-process mode (default) with
> `--astf-flush-on-pass=ON` and `--astf-t-duration=10` for any topology with
> stateful connection tracking. The subprocess model (`--astf-use-subprocess`) is
> deprecated for performance evaluation and may be removed in a future release.

### TRex DP Core Distribution

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--astf-per-core-distribution` | `seq` | Controls how TRex distributes source IPs across its data-plane (DP) cores. Values: `seq` (exclusive IP subsets per core) or `default` (shared IP pool across all cores). |
| `--astf-ip-offset-server` | (empty) | Independent server-side IP offset per dual-port pair. When empty, uses the same offset as `--astf-ip-offset`. |

**`seq` mode** (recommended): Each DP core gets an exclusive subset of the
client/server IP range. This eliminates cross-core contention for the same
5-tuple space and produces lower retransmits, better RTT, and faster
convergence. See "Per-Core IP Distribution Mode" for a detailed comparison.

**`default` mode**: All DP cores share the full IP pool. This can cause
duplicate 5-tuples across cores, leading to higher retransmits and conntrack
confusion under load.

```json
{ "arg": "astf-per-core-distribution", "vals": ["seq"], "role": "client" }
```

The `--astf-ip-offset-server` parameter is used when the DUT has asymmetric
routing (e.g., L3 forwarder where client and server subnets route through
different interfaces). In most OVS-DPDK topologies with testpmd mac-forward,
this is not needed.

### External Profile

### Error Counter Reference (`--astf-ignore-errors`)

Phase 2 of `evaluate_trial_astf()` checks for catastrophic ASTF errors that
indicate infrastructure problems (not DUT load). By default, ANY of these
counters being non-zero causes an immediate hard-fail:

| Counter | Meaning | Default behavior |
|---------|---------|-----------------|
| `err_flow_overflow` | TRex internal flow table full | Hard-fail (always) |
| `err_cwf` | Client packet arrived at a port that doesn't own the flow | Hard-fail (default) |
| `err_s_nf_throttled` | TRex server new-flow creation throttled | Hard-fail (default) |
| `err_no_memory` | TRex out of memory | Hard-fail (always) |
| `err_dport_map` | Destination port mapping error | Hard-fail (always) |

Use `--astf-ignore-errors` to move specific counters from Phase 2 (hard-fail)
to Phase 3/4 (percentage evaluation). The counters are still collected, logged,
and reported in metrics -- only their pass/fail behavior changes.

**When to use `--astf-ignore-errors`:**

| Topology | Counter to ignore | Why |
|----------|-------------------|-----|
| OVS-DPDK + VM testpmd mac-fwd | `err_cwf` | testpmd mac-forward returns packets to the paired port; OVS delivers to the "wrong" TRex port. Connections still complete (0% error). |
| High-CPS with flow table pressure | `err_s_nf_throttled` | At extreme CPS, TRex may temporarily throttle new server flows. If connections still succeed at the target rate, throttling is acceptable. |

**When NOT to use `--astf-ignore-errors`:**

| Topology | Why counters should remain catastrophic |
|----------|----------------------------------------|
| Bare-metal testpmd (direct cable) | `err_cwf` means packets are arriving at the wrong physical port -- cabling or MAC config is wrong |
| L3 DUT (OVS router, NAT, firewall) | `err_cwf` means the DUT is routing packets incorrectly |
| Any topology with `err_flow_overflow` | TRex flow table full means test parameters exceed TRex capacity -- increase `--astf-max-flows` instead |

**Example: OVS-DPDK HTTP-like TCP test**

```json
{ "arg": "astf-ignore-errors", "vals": ["err_cwf"], "role": "client" }
```

With this setting, a trial producing `err_cwf: 500024, connection_error_pct: 0.0%`
will proceed to Phase 3 (where 0.0% < 0.1% threshold = pass) instead of
hard-failing at Phase 2.

**Example: High-CPS stress test allowing throttling**

```json
{ "arg": "astf-ignore-errors", "vals": ["err_cwf,err_s_nf_throttled"], "role": "client" }
```

Multiple counters are comma-separated in a single value string.

**Example: Bare-metal testpmd (no ignore needed)**

Do NOT set `--astf-ignore-errors` for direct-cable topologies. If you see
`err_cwf` in this setup, it indicates a real MAC/port configuration problem
that must be fixed, not ignored.

### Flow Timeout Control (`--astf-e-duration`, `--astf-t-duration`)

These parameters bound the time TRex spends on flow lifecycle:

| Parameter | Effect when set | Effect when 0 (default) |
|-----------|----------------|------------------------|
| `--astf-e-duration=10` | Abandon flows not established within 10s | Use TCP default (~63s retransmit timeout) |
| `--astf-t-duration=10` | Wait up to 10s for FIN/ACK after stop | Force-close all flows immediately |

**When to use:**

| Scenario | Recommended setting | Why |
|----------|--------------------|----|
| OVS-DPDK with conntrack | `e-duration=10, t-duration=10` | Prevents hang if OVS upcall is slow; cleaner conntrack state |
| Binary search (any topology) | `e-duration=10` | Prevents stuck trials when search probes above DUT capacity |
| One-shot validation | `t-duration=30` | Ensures all connections close gracefully for accurate final stats |
| Bare-metal testpmd (direct) | Not needed (default 0) | Direct connections establish instantly |

**Example profile (OVS-DPDK):**

```json
{ "arg": "astf-e-duration", "vals": ["10"], "role": "client" },
{ "arg": "astf-t-duration", "vals": ["10"], "role": "client" }
```

### External Profile

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--astf-profile` | (none) | Path to external `.py` ASTF profile file |

Using an external profile overrides all built-in profile parameters.

## NFV Test Scenarios

### Scenario 1: Short-Lived TCP (Conntrack INSERT/DELETE Stress)

**Objective**: Find maximum CPS where OVS conntrack can create and destroy entries.

```bash
--astf-profile=trafficgen/astf-profiles/short-lived-tcp.py
--astf-max-flows=50000
--astf-ramp-time=10
```

Expected: 30K-100K+ CPS depending on hardware and OVS PMD thread count.
Conntrack flush between trials is not required (see "Conntrack Flush Between
Trials" in the DUT Setup section).

### Scenario 2: Long-Lived TCP (Conntrack Lookup Stress)

**Objective**: Find maximum CPS where OVS conntrack can sustain concurrent flow lookups.

```bash
--astf-profile=trafficgen/astf-profiles/long-lived-tcp.py
--astf-max-flows=500000
--astf-ramp-time=30
--search-runtime=120
```

Expected: 500-5K CPS with large active flow tables stressing lock contention.

### Scenario 3: Short-Lived UDP

**Objective**: Validate UDP conntrack tracking (different state machine from TCP).

```bash
--astf-profile=trafficgen/astf-profiles/short-lived-udp.py
--astf-max-flows=50000
```

### Scenario 4: Mixed TCP+UDP (Realistic NFV)

**Objective**: Simulate 99% TCP + 1% UDP realistic NFV traffic mix.

```bash
--astf-protocol=mixed
--astf-udp-percent=1.0
--astf-num-messages=1
--astf-message-size=20
```

### Scenario 5: HTTP-Like TCP (Application Layer)

**Objective**: Stress conntrack with real HTTP-sized payloads and multiple exchanges.

```bash
--astf-profile=trafficgen/astf-profiles/http-like-tcp.py
--astf-max-flows=50000
```

## OVS+Conntrack DUT Setup Reference

### Conntrack Table Sizing

The steady-state conntrack entry count depends on CPS and the conntrack
timeout for the connection state:

```
steady_state_entries ≈ CPS × conntrack_timeout_sec
```

| Profile | CPS (example) | Timeout used | Steady-state entries | Required nf_conntrack_max |
|---------|--------------|--------------|---------------------|--------------------------|
| Short-lived TCP | 37,000 | tcp_established=30s | ~1.1M | 2M+ |
| Long-lived TCP | 5,000 | tcp_established=30s | ~150K | 500K+ |
| Short-lived UDP | 50,000 | udp_single=1s | ~50K | 200K+ |
| Mixed TCP+UDP | 30,000 | tcp=30s, udp=1s | ~900K | 2M+ |
| HTTP-like TCP | 20,000 | tcp_established=30s | ~600K | 1M+ |

### Kernel Conntrack Timeout Tuning

The kernel conntrack timeouts apply to host-level connections (SSH, Redis,
monitoring), NOT to OVS-DPDK data-plane traffic. OVS-DPDK uses its own
userspace conntrack table with zone timeout policies (see "OVS Zone Timeout
Policy" below). The kernel and OVS conntrack tables are independent.

Kernel defaults (e.g., `tcp_established=432000` / 5 days) will exhaust
the kernel conntrack table from management traffic during sustained testing.

Apply on the compute host running OVS-DPDK:

```bash
# 120s provides margin for 60-90s ASTF trials without expiring infrastructure
# TCP connections (Redis heartbeats, SSH). Do NOT set below 120s if the host
# uses nftables with INPUT policy drop -- expired entries cause nftables to
# drop return packets, breaking roadblock heartbeats (RC=5 timeout).
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=120

sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=1
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_fin_wait=1
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_close_wait=1
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_syn_sent=1
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_syn_recv=1
sysctl -w net.netfilter.nf_conntrack_max=10000000
```

**Why 120s, not 30s**: Earlier guidance recommended 30s to match the OVS zone
`tcp_established` timeout. However, 30s is too aggressive for the kernel table.
During a 60-second ASTF trial under high CPU load, idle infrastructure TCP
connections (Crucible's Redis-based roadblock heartbeats) have their kernel
conntrack entries expire. On hosts with nftables `INPUT policy drop`, the
expired entries cause return packets to be dropped as untracked "new"
connections. This manifests as heartbeat timeouts (RC=5) and test aborts.
The 120s value keeps infrastructure connections alive through the longest
typical trial duration (90s) plus inter-trial overhead.

### OVS Physical Port RX Queue Tuning

For multi-port-pair deployments with high aggregate CPS, configure multiple RX
queues on each physical DPDK port to distribute traffic across PMD threads:

```bash
ovs-vsctl set Interface dpdk-p0 options:n_rxq=4
ovs-vsctl set Interface dpdk-p1 options:n_rxq=4
# Repeat for all physical DPDK ports in the bridge
```

| n_rxq | PMD threads per port | Typical per-thread utilization at 50K CPS (4 pairs) |
|-------|---------------------|-----------------------------------------------------|
| 1 (default) | 1 | ~50% (bottleneck) |
| 2 | 2 | ~25% |
| 4 | 4 | ~12-15% (recommended) |

Verify assignment with `ovs-appctl dpif-netdev/pmd-rxq-show`. Each queue should
map to a distinct PMD core. If multiple queues map to the same core, adjust CPU
affinity with `ovs-vsctl set Open_vSwitch . other_config:pmd-cpu-mask=<mask>`.

### OVS Zone Timeout Policy

Configure OVS conntrack zone timeouts on the compute host:

```bash
ovs-vsctl add-zone-tp netdev zone=0 \
    tcp_syn_sent=1 tcp_syn_recv=1 tcp_established=30 \
    tcp_fin_wait=1 tcp_time_wait=1 tcp_close=1 \
    udp_first=1 udp_single=1 udp_multiple=30
```

These values work for all profile types:
- **Short-lived TCP/UDP**: connections close quickly; 30s established
  timeout provides a buffer for retransmits without accumulating entries.
- **Long-lived TCP**: connections stay in ESTABLISHED state; 30s timeout
  clears entries after the connection closes naturally.
- **Mixed**: TCP uses 30s established, UDP uses 1s (single) / 30s (stream).

### Conntrack Flush Between Trials (Smart Pre-Trial-Cmd)

For OVS-DPDK deployments with conntrack, flushing the OVS datapath conntrack
table between trials can improve convergence by removing stale entries from
the previous trial. The `--pre-trial-cmd` parameter supports this with a
**smart flush** strategy that selectively flushes only when beneficial:

| Condition | Flush? | Rationale |
|-----------|--------|-----------|
| First trial | Yes | Start with a clean conntrack table |
| After a failed trial | Yes | Clear stale entries that may have caused the failure |
| Before validation trial | Yes | Ensure clean state for the final validation |
| After a passing search trial | No | Avoid disrupting a working DUT state |

**Important**: OVS-DPDK uses a userspace conntrack table, not the kernel
conntrack table. Use `ovs-appctl dpctl/flush-conntrack` (not `conntrack -F`)
to flush it. The `--pre-trial-cmd` executes on the TRex client host inside
a chroot container, so an SSH wrapper script is needed to run commands on
the remote compute host.

**Step 1: Create the flush wrapper script on the TRex client host**

```bash
cat > /root/flush-ovs-conntrack.sh << 'SCRIPT'
#!/bin/bash
ssh -o BatchMode=yes -o ConnectTimeout=5 <compute-host> \
    "ovs-appctl dpctl/flush-conntrack"
SCRIPT
chmod +x /root/flush-ovs-conntrack.sh
```

Replace `<compute-host>` with the hostname or IP of the OVS-DPDK compute node.

**Step 2: Configure passwordless SSH from TRex client to compute host**

```bash
# On the TRex client host:
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
ssh-copy-id root@<compute-host>
ssh-keyscan <compute-host> >> ~/.ssh/known_hosts

# Verify:
ssh -o BatchMode=yes <compute-host> "ovs-appctl dpctl/ct-get-nconns"
```

**Step 3: Configure the Crucible profile**

The TRex client engine runs inside a chroot container. To access the host's
SSH keys and flush script, mount the host `/root` directory:

```json
"config": {
    "settings": {
        "osruntime": "chroot",
        "host-mounts": [{ "src": "/root", "dest": "/root" }]
    }
}
```

Then add `--pre-trial-cmd` to the client parameters:

```json
{ "arg": "pre-trial-cmd", "vals": ["/root/flush-ovs-conntrack.sh"], "role": "client" }
```

The smart flush logic in `binary-search.py` will execute the script only on
the first trial, after a failed trial, and before validation -- skipping it
after passing search trials to avoid unnecessary disruption.

| Condition | Flush? | Rationale |
|-----------|--------|-----------|
| After a passing search trial + `astf-flush-on-pass=ON` | **Yes** | Full per-trial isolation for conntrack-sensitive DUTs |

> **For conntrack-sensitive DUTs (OVS-DPDK)**, the default smart flush strategy
> is not sufficient when using in-process mode, because `client.update()` keeps
> traffic running and conntrack entries accumulate across passes. Enable
> `--astf-flush-on-pass=ON` to force flush after every trial, including passes.
> This ensures each trial starts from a clean conntrack state at the cost of
> ~10-20s additional ramp-up per trial. See
> [In-Process Persistent Connection Mode](#in-process-persistent-connection-mode)
> for details.

## ASTF Binary Search Flow

```
binary-search.py starts
  └─ rate = initial_rate (default 100.0 × ASTF_MULTIPLIER = 10000 CPS)
  │
  ├─ if --uniform-trial-runtime is set:
  │     search_runtime = validation_runtime = uniform_trial_runtime
  │
  ├─ get_trex_port_info() → trex-astf-query.py → ASTFClient.get_port_attr()
  │
  ├─ [In-process mode (default)]:
  │    setup_astf_client() → connect → configure_ports → load_profile
  │
  └─ Search Loop:
       │
       ├─ If validation trial AND in-process:
       │    client.stop() → sleep(astf_t_duration) → traffic_running=False
       │
       ├─ Smart pre-trial-cmd decision:
       │    should_flush = (first_trial OR prev_failed OR is_validation
       │                    OR flush_on_pass_stopped OR force_next_flush)
       │    if should_flush AND --pre-trial-cmd is set:
       │        run --pre-trial-cmd (e.g., flush OVS conntrack)
       │    else:
       │        skip (preserve working DUT state after passing search trials)
       │
       ├─ [In-process mode (default)]:
       │    ├─ if traffic_running:
       │    │    sample directly (traffic already at target rate)
       │    ├─ else:
       │    │    client.start(mult) → wait_for_cps_stable() → sample
       │    ├─ clear_stats() → start_latency() → sleep(runtime)
       │    ├─ get_stats() → get_flow_info() → aggregate TCP RTT
       │    ├─ stop_latency()
       │    └─ After trial:
       │         pass + flush-on-pass? → client.stop() + sleep(t_duration)
       │         pass + default?       → client.update(new_mult)
       │         fail?                 → client.stop() + sleep(t_duration)
       │
       ├─ [Subprocess mode (--astf-use-subprocess, deprecated)]:
       │    ├─ Spawn: trex-astf.py --mult=rate
       │    │    ├─ ASTFClient.connect()
       │    │    ├─ reset() → set_l2_mode(dst_mac)
       │    │    ├─ load_profile() → start(mult=rate)
       │    │    ├─ wait_for_cps_stable() → sample → stop() → disconnect()
       │    │    └─ emit "PARSABLE RESULT: {astf_json}" on stderr
       │
       ├─ evaluate_trial_astf():
       │    Phase 1:  connections_attempted == 0? → abort
       │    Phase 1b: CPS near zero with no connections? → fail (traffic collapse)
       │    Phase 1c: active_flows >= 95% of astf-max-flows? → fail (flow saturation)
       │    Phase 2:  catastrophic ASTF errors (err_flow_overflow, etc.)? → fail
       │              Counters listed in --astf-ignore-errors are excluded.
       │    Phase 3:  connection_error_pct > --astf-max-error-pct? → fail
       │    Phase 4:  retransmit_pct > --astf-max-retransmit-pct? → fail (opt.)
       │    Phase 5:  UDP drop > --astf-max-udp-drop-pct (pure UDP + mixed)? → fail
       │    Phase 6:  CPS under-delivery > --astf-max-cps-deviation-pct? → fail
       │    Phase 7:  timeout/force_quit? → retry/quit
       │
       ├─ Auto-recovery: if 2+ consecutive false-positive removals detected
       │    → client.stop() + flush → breaks conntrack accumulation cascade
       │
       ├─ pass? → lower = rate, rate = (lower+upper)/2
       ├─ fail? → upper = rate, rate = (lower+upper)/2
       └─ converged? → Final Validation Trial → binary-search.json
```

## PARSABLE RESULT Format

`trex-astf.py` emits a single `PARSABLE RESULT: {json}` line on stderr.

Key fields in the ASTF result JSON:

```json
{
  "trial_start": 1714000000000,
  "trial_stop":  1714000035000,
  "global": {
    "runtime":      30.0,
    "tx_cps":       9850.5,
    "active_flows": 49200,
    "tx_pps":       125000.0,
    "rx_pps":       123500.0
  },
  "total": {
    "opackets": 3750000,
    "ipackets": 3705000
  },
  "astf": {
    "client": {
      "tcps_connattempt":  295500,
      "tcps_connects":     295200,
      "tcps_closed":       246000,
      "tcps_drops":           300,
      "tcps_sndpack":      887100,
      "tcps_sndrexmitpack":   900,
      "m_active_flows":    49200,
      "m_tx_bw_l7_r":    625000000.0
    },
    "has_astf_errors": false,
    "err": {}
  },
  "tcp_info": {
    "tcp_rtt_avg_usec": 85.5,
    "tcp_rtt_min_usec": 31.25,
    "tcp_rtt_max_usec": 281.25,
    "tcp_rtt_samples": 10,
    "tcp_rto_avg_usec": 230000.0
  }
}
```

## KPIs Reported

| KPI | Source | Description |
|-----|--------|-------------|
| **CPS** | `global.tx_cps` | Connections per second (primary search metric) |
| **Active Flows** | `astf.client.m_active_flows` | Concurrent connections |
| **Connection Error %** | `drops/attempts × 100` | Primary pass/fail gate |
| **Retransmit %** | `sndrexmitpack/sndpack × 100` | TCP health indicator |
| **Out-of-Order %** | `rcvoopack/rcvpack × 100` | DUT reordering indicator |
| **TCP RTT avg** | `tcp_info.tcp_rtt_avg_usec` | Real data-path latency from get_flow_info() |
| **TCP RTT min/max** | `tcp_info.tcp_rtt_min/max_usec` | Best/worst case DUT forwarding latency |
| **L7 TX/RX BW** | `m_tx_bw_l7_r`, `m_rx_bw_l7_r` | Application-layer bandwidth |

## Multi-Port-Pair Traffic Distribution

ASTF distributes traffic across port pairs differently from STL:

- **ASTF**: A single `c.start(mult=M)` call applies the CPS multiplier evenly across
  all active port pairs. Per-pair IP isolation is provided by
  `ASTFIPGenGlobal(ip_offset="1.0.0.0")`, which automatically offsets the client and
  server IP ranges for each successive dual-port pair:
  - Pair 0:1 -- client 16.0.0.0/16, server 48.0.0.0/16
  - Pair 2:3 -- client 17.0.0.0/16, server 49.0.0.0/16 (offset +1.0.0.0)
  - Pair 4:5 -- client 18.0.0.0/16, server 50.0.0.0/16 (offset +2.0.0.0)
  - Pair 6:7 -- client 19.0.0.0/16, server 51.0.0.0/16 (offset +3.0.0.0)

- **STL** (trex-txrx / trex-txrx-profile): Each port pair has independent per-stream
  rate control. Streams are added to individual ports with their own PPS rates and
  pg_id tracking.

The `--active-device-pairs` parameter controls which pairs participate in each trial.
This is the same mechanism used by TRex's upstream `cps_ndr.py` script.

### OVS-DPDK Multi-Port-Pair Deployment

For OVS-DPDK deployments where TRex connects to a VM through an OVS bridge,
explicit L2 MAC configuration is required on both client and server sides.

**Topology (4 port pairs through OVS-DPDK to VM with testpmd mac-fwd):**

```
TRex (8 ports, 4 pairs)          OVS-DPDK Bridge          VM testpmd (8 Virtio ports)
  Port 0 (40:a6:b7:...:ac) ──→  br-int ──→ vhost ──→  Virtio 0 (fa:16:3e:94:cd:12)
  Port 1 (40:a6:b7:...:ad) ←──  br-int ←── vhost ←──  Virtio 1 (fa:16:3e:0a:3c:87)
  Port 2 (3c:fd:fe:...:c0) ──→  br-int ──→ vhost ──→  Virtio 2 (fa:16:3e:4e:cc:dc)
  Port 3 (3c:fd:fe:...:c1) ←──  br-int ←── vhost ←──  Virtio 3 (fa:16:3e:02:87:67)
  ... (same pattern for pairs 4:5 and 6:7)
```

**Required profile parameters:**

Client side -- tell TRex the VM's Virtio MACs (so `set_l2_mode()` configures
the correct destination MAC per port):

```json
{ "arg": "dst-macs", "vals": ["<virtio0-mac>,<virtio1-mac>,...,<virtio7-mac>"], "role": "client" }
```

Server side -- tell testpmd the TRex port MACs for mac-forward mode
(`--eth-peer` swaps destination MAC on return path):

```json
{ "arg": "testpmd-forward-mode", "vals": ["mac"], "role": "server" }
{ "arg": "testpmd-dst-macs", "vals": ["<trex-port0-mac>,...,<trex-port7-mac>"], "role": "server" }
```

TRex enables service mode to configure L2 mode (`set_l2_mode(port, dst_mac)`)
on each port, then disables service mode before starting traffic. This sets
explicit destination MACs so packets reach the correct OVS vhost-user port
without requiring ARP resolution.

**Handling `err_cwf` in OVS-DPDK with testpmd mac-forward:**

In OVS-DPDK topologies with testpmd `mac` forwarding mode, the `err_cwf`
(client packet without flow) counter fires at approximately 50% of connection
attempts. This is expected behavior -- packets returning through the OVS bridge
arrive at the paired TRex port rather than the originating port due to the
testpmd port-pair forwarding model. Connections still complete with 0% error
rate because TRex's ASTF stack processes the packet regardless of which port
it arrives on.

To prevent Phase 2 from hard-failing on this counter:

```json
{ "arg": "astf-ignore-errors", "vals": ["err_cwf"], "role": "client" }
```

This is required for HTTP-like TCP and long-lived TCP profiles on OVS-DPDK
where connections have multiple packets and `err_cwf` accumulates proportionally
to traffic volume. Short-lived TCP (64B x 1 msg) may also need it depending on
the OVS flow learning timing.

**How the binary search converges (validated 4-pair short-lived TCP result):**

The search starts at the configured `--rate` ceiling (e.g., 500K CPS) and
performs a binary search to find the maximum rate where the DUT passes all
7 evaluation phases. In the OVS-DPDK topology, the convergence pattern is:

```
Trial  1: 50,000 CPS → pass (search)
Trial  2: 50,000 CPS → fail (validation -- retransmits under sustained 60s load)
Trial  3: 49,950 CPS → fail (retransmit % too high)
Trial  4: 24,981 CPS → pass
Trial  5: 37,356 CPS → pass
Trial  6: 43,557 CPS → fail (retransmit %)
  ... binary search narrows the range ...
Trial 13: 37,354 CPS → pass (search converged)
Trial 14: 37,527 CPS → pass (final validation, 60 seconds)
  NDR = 37,527 CPS across 4 port pairs
```

Traffic distributes evenly across all 4 port pairs (~2.3M TX packets per
client port during the 60-second validation). Per-pair CPS is approximately
NDR / num_pairs (e.g., ~9,400 CPS per pair for 37,527 aggregate).

**Validated metrics at NDR (4 pairs, 64B x 1 msg, OVS-DPDK + VM testpmd):**

| Metric | Value |
|--------|-------|
| NDR CPS | 37,527 |
| Active flows | 21,525 |
| Connection error % | 0.0% |
| TCP retransmit % | 0.0% |
| TCP RTT avg / min / max | 85.5 / 31.2 / 281.2 usec |

### Per-Core IP Distribution Mode

The `--astf-per-core-distribution` parameter controls how TRex assigns source
IPs to its DP (data-plane) cores:

**`seq` (sequential, recommended)**: Each DP core gets an exclusive, contiguous
subset of the IP range. For example, with 8 DP cores and a /16 client range
(65536 IPs), each core owns ~8192 IPs. This eliminates cross-core 5-tuple
collisions.

**`default` (shared pool)**: All DP cores draw from the full IP range. Multiple
cores can generate packets with the same source IP simultaneously, leading to
duplicate 5-tuples, retransmit confusion, and higher conntrack churn on the DUT.

**Comparison from OVS-DPDK testing (4 port pairs, short-lived TCP 64B x 1 msg):**

| Metric | `default` | `seq` | Improvement |
|--------|-----------|-------|-------------|
| Converged CPS | ~52,000 | ~52,000 | Same throughput |
| Trials to converge | 31 | 16 | 48% fewer trials |
| TCP RTT avg (usec) | 268 | 84 | 3.2x lower latency |
| TCP retransmit % | 0.07% | 0.04% | 43% fewer retransmits |
| OVS conntrack entries | 29,853 | 24,772 | 17% fewer entries |

The `seq` mode achieves the same peak CPS with significantly better efficiency:
fewer trials (faster convergence), lower latency, fewer retransmits, and a
smaller conntrack footprint. Use `seq` for production testing.

## In-Process Persistent Connection Mode

By default, ASTF uses a **persistent in-process `ASTFClient` connection** across
all trials in a binary search. Instead of spawning a new `trex-astf.py` subprocess
for each trial (connecting, loading the profile, starting, sampling, stopping,
disconnecting), the in-process mode maintains a single connection and uses
`client.update(mult)` to change the CPS rate between trials without stopping traffic.

This is the **recommended production mode** for all CPS evaluation. The legacy
subprocess model (`--astf-use-subprocess`) is deprecated for performance measurement
and retained only as a diagnostic tool for developers.

### Execution Modes Comparison

| Aspect | Subprocess (deprecated) | In-process (default) | In-process + flush-on-pass |
|--------|------------------------|---------------------|---------------------------|
| Connection | New per trial | Persistent across search | Persistent across search |
| Rate change | reconnect/reload/start | `client.update(mult)` | `client.stop()` / `client.start()` |
| Per-trial overhead | ~20s (connect + profile load + ramp) | ~0s (hot update) | ~10-20s (ramp only, no reload) |
| Conntrack accumulation | None (natural cooling) | Accumulates on passes | None (flushed per trial) |
| Best for | Debugging only | Bare-metal, hardware DUTs | **OVS-DPDK, stateful firewalls, NAT** |
| Recommendation | Not for production use | Production (stateless DUTs) | **Production (stateful DUTs)** |

> **Deprecation Notice**: The subprocess-per-trial model (`--astf-use-subprocess`)
> is deprecated for CPS performance evaluation. It is retained solely as a
> diagnostic tool for developers. The in-process mode with `--astf-flush-on-pass=ON`
> achieves equivalent per-trial isolation with better accuracy (86K vs 83K CPS on
> the same topology) and without the oscillation problems observed in subprocess
> mode at fine search granularity.

### Conntrack-Sensitive DUTs and astf-flush-on-pass

When testing through **stateful DUTs** (OVS-DPDK with conntrack, iptables/nftables
firewalls, NAT gateways), the default in-process hot-update path creates a problem:

1. Trial N passes at rate X -- traffic continues running
2. `client.update(new_rate)` changes CPS without stopping
3. Active TCP flows from trial N persist in both TRex and the DUT's conntrack table
4. Trial N+1 inherits accumulated conntrack state from trial N
5. The stale state causes retransmit spikes, making the next trial fail at rates
   that would pass on clean conntrack

The `--astf-flush-on-pass` parameter solves this by forcing a full stop/flush/start
cycle after every trial, including passes:

```json
{ "arg": "astf-flush-on-pass", "vals": ["ON"], "role": "client" }
```

When enabled, after every passing trial:
1. `client.stop()` -- drains all active TRex flows
2. `sleep(astf_t_duration)` -- waits for graceful TCP teardown (configurable)
3. `pre-trial-cmd` executes -- flushes OVS conntrack table
4. `client.start(new_rate)` -- fresh start at the next search rate

This provides the same per-trial isolation as the subprocess model without the
reconnect/reload overhead (~10-20s per trial vs ~20s+).

**When to use `--astf-flush-on-pass=ON`:**
- OVS-DPDK with conntrack (userspace flow tracking)
- iptables/nftables stateful firewall DUTs
- NAT gateway testing
- Any DUT where connection state persists between rate changes

**When to leave it OFF (default):**
- Bare-metal NICs with no stateful processing
- Hardware offload DUTs (SmartNICs)
- Environments where conntrack is disabled

### False-Positive Collapse Auto-Recovery

In-process mode includes automatic detection of **false-positive collapse** -- a
pathological pattern where the binary search passes at a rate, then fails at the
same or lower rate due to accumulated conntrack state.

When 2 or more consecutive "false positive" passes are detected and removed from
the search stack, the system automatically:
1. Stops traffic (`client.stop()`)
2. Waits for teardown (`astf-t-duration`)
3. Forces a conntrack flush on the next trial
4. Resets the false-positive counter

This is fully automatic -- no parameter needed. It only activates for in-process
mode when traffic is running. The mechanism prevents the search from wasting many
trials descending through stale-state failures before recovering.

### Validation Trial Clean-State Guarantee

Regardless of `--astf-flush-on-pass` setting, the in-process mode **always** stops
traffic before the final validation trial:

```
Trial Mode: Final Validation
ASTF in-process: stopping traffic before validation (clean conntrack)
ASTF in-process: waiting 10s for teardown before validation
Running pre-trial-cmd (flush-on-pass (traffic stopped))
Executing pre-trial-cmd [/root/flush-ovs-conntrack.sh]
```

This ensures:
- All TRex flows drain before the flush script runs
- The conntrack flush is effective (no active traffic re-creating entries)
- The validation measurement starts from a clean state
- The final result is equivalent to what a fresh subprocess trial would produce

### OVS-DPDK Performance Results

Validated on OVS-DPDK with 4 port pairs (8x25G XXV710 → OVS conntrack → VM testpmd mac-fwd):

**Multi-Protocol CPS Comparison (in-process + flush-on-pass, granularity=0.1%):**

| Protocol | UDP Drop Threshold | CPS (NDR) | Trials | Primary Fail Signal |
|----------|-------------------|-----------|--------|---------------------|
| **TCP** | N/A | **86,255** | 15 | Phase 4: retx > 20% |
| **UDP** | 5% (default) | **59,066** | 15 | Phase 5: UDP drop > 5% |
| **Mixed (1% UDP)** | 20% | **66,335** | 34 | Phase 4: retx > 20% |

**Why TCP > Mixed > UDP on conntrack-sensitive DUTs:**

- **TCP (86K CPS):** TCP flows have active teardown (FIN/RST) that clears conntrack
  entries. The retransmit threshold (20%) provides a clean, deterministic boundary.
  OVS handles TCP flows efficiently because conntrack state transitions are well-defined.

- **UDP (59K CPS):** UDP flows have no teardown -- they persist in conntrack until
  timeout expiry. This creates higher conntrack table pressure per CPS. The 5% packet
  drop threshold detects when OVS starts shedding UDP packets under load.

- **Mixed 1% UDP (66K CPS):** The 99% TCP component is healthy at 66K but the 1%
  UDP acts as a sensitive indicator of DUT stress. With a relaxed 20% UDP drop
  threshold, the NDR is governed by TCP retransmits (the majority traffic). Without
  the relaxed threshold, the NDR drops to ~54K due to minor UDP drops that don't
  impact overall connection quality.

**In-process mode progression (TCP, showing improvement over subprocess):**

| Mode | CPS (NDR) | Trials | Convergence |
|------|-----------|--------|-------------|
| Subprocess (deprecated) | 83,214 | 11 | Clean but limited |
| In-process (no flush-on-pass) | 78,232 | 23 | False-positive collapse |
| **In-process + flush-on-pass** | **86,255** | **15** | **Clean, monotonic** |

**Recommended OVS-DPDK TCP profile parameters:**

```json
{ "arg": "astf-flush-on-pass", "vals": ["ON"], "role": "client" },
{ "arg": "astf-t-duration", "vals": ["10"], "role": "client" },
{ "arg": "astf-per-core-distribution", "vals": ["seq"], "role": "client" },
{ "arg": "uniform-trial-runtime", "vals": ["60"], "role": "client" },
{ "arg": "search-granularity", "vals": ["0.1"], "role": "client" },
{ "arg": "pre-trial-cmd", "vals": ["/root/flush-ovs-conntrack.sh"], "role": "client" },
{ "arg": "astf-max-retransmit-pct", "vals": ["20.0"], "role": "client" },
{ "arg": "astf-ignore-errors", "vals": ["err_cwf"], "role": "client" }
```

| Parameter | Value | Role in OVS-DPDK topology |
|-----------|-------|--------------------------|
| `astf-flush-on-pass` | ON | Per-trial conntrack isolation |
| `astf-t-duration` | 10 | Teardown wait for TCP FIN/RST to reach OVS before flush |
| `astf-per-core-distribution` | seq | Exclusive IP subsets per DP core, reduces cross-core contention |
| `uniform-trial-runtime` | 60 | Same duration for search and validation, prevents conntrack asymmetry |
| `search-granularity` | 0.1 | Fine-grained convergence (finds higher NDR than coarse granularity) |
| `pre-trial-cmd` | flush script | SSH wrapper to run `ovs-appctl dpctl/flush-conntrack` on compute host |
| `astf-max-retransmit-pct` | 20.0 | Relaxed threshold for OVS-DPDK (more retransmits than bare-metal) |
| `astf-ignore-errors` | err_cwf | Expected in testpmd mac-fwd topology; connections still complete |

### OVS-DPDK Conntrack Learning Points

Key observations from multi-protocol validation on OVS-DPDK with conntrack:

1. **TCP retransmit is a deterministic boundary.** The binary search converges
   cleanly in ~15 trials because TCP retransmit rates cross the threshold
   predictably as CPS increases. OVS conntrack handles TCP state transitions
   efficiently -- the NDR boundary is stable and reproducible.

2. **UDP flows don't close actively.** Without FIN/RST teardown, UDP flows
   persist in both the TRex flow table and OVS conntrack until timeout expiry.
   The `astf-max-flows` parameter must be sized to prevent flow table saturation
   (recommended: `expected_NDR * 2`, not 1,000,000).

3. **Mixed mode needs separate UDP drop threshold.** With 1% UDP, the minority
   protocol is disproportionately sensitive to DUT stress. Setting
   `--astf-max-udp-drop-pct=20` (vs the 5% default) allows the search to
   converge on the TCP retransmit boundary instead of the UDP drop boundary,
   raising NDR by ~23%.

4. **Stochastic boundaries require retries.** In mixed mode, the same CPS rate
   can pass or fail depending on OVS conntrack timing variance. Setting
   `--max-retries=2` prevents single bad trials from incorrectly failing the
   search at the convergence boundary.

5. **Flow table saturation detection is critical for UDP.** Without Phase 1c
   (active_flows >= 95% of max), UDP trials appear to "pass" with 0% errors
   despite severely collapsed CPS. The flow table silently throttles new
   connections without generating error counters.

6. **UDP flow drain requires `client.reset()`.** After `client.stop()`, TCP
   flows drain via FIN/RST within `astf-t-duration` seconds. UDP flows have
   no teardown signal -- the in-process mode automatically calls
   `client.reset()` after stop for UDP/mixed protocols to clear the internal
   flow table before the next trial.

### Trial Duration Breakdown

The `binary-search.search-summary.txt.xz` file shows wall-clock duration per trial.
With `uniform-trial-runtime=60`, each trial takes ~80 seconds:

```
  # | Start Time - Stop Time                        | Duration |        Rate |       Type |    CPS | Err% | Result
  4 | 2026-05-28 01:18:42 - 2026-05-28 01:20:02    |  79.82s  |  62500 cps  |     search | 62495  |  0.1 | pass
 14 | 2026-05-28 01:34:45 - 2026-05-28 01:36:04    |  79.77s  |  86461 cps  |     search | 86204  |  0.1 | pass
 15 | 2026-05-28 01:36:18 - 2026-05-28 01:37:38    |  79.77s  |  86505 cps  | validation | 86255  |  0.1 | pass
```

The ~80s total is composed of:

| Phase | Duration | Notes |
|-------|----------|-------|
| `client.start(mult)` | ~0.5s | TRex API call to begin traffic |
| CPS ramp-up | ~14s | `astf-ramp-time=10` + tolerance stabilization |
| Clear stats + start latency probes | ~0.01s | Reset counters before measurement |
| **Traffic sampling** | **60s** | The `uniform-trial-runtime` value |
| TCP RTT flow sampling | ~5s | `poll=5.0s` to collect flow-level RTT |
| Stats aggregation | ~0.02s | Compute CPS, retx%, error% |
| **Total wall-clock** | **~79-82s** | |

The 60s `uniform-trial-runtime` controls only the steady-state measurement window.
The ramp-up (~14s) ensures CPS is stable before sampling begins, and the RTT
collection (~5s) provides per-flow latency data. These are not overhead -- they are
essential for accurate measurement on OVS-DPDK where CPS takes 10-15 seconds to
reach target rate through the conntrack datapath.

### Reading the Logs

Key log patterns to look for when reviewing ASTF in-process run output:

**Mode announcement (at startup):**
```
ASTF mode: in-process persistent connection (use --astf-use-subprocess for legacy mode)
```

**Flush-on-pass behavior (after every passing trial):**
```
(trial passed all requirements)
ASTF in-process: stopping traffic after pass (flush-on-pass enabled)
```

**Validation stop (before final validation only):**
```
Trial Mode: Final Validation
ASTF in-process: stopping traffic before validation (clean conntrack)
ASTF in-process: waiting 10s for teardown before validation
Running pre-trial-cmd (flush-on-pass (traffic stopped))
```

**Teardown wait on failure:**
```
ASTF in-process: stopping traffic for rate change (trial fail)
ASTF in-process: waiting 10s for teardown
```

**False-positive collapse detection (automatic):**
```
Removing false positive passing result: 127,000
ASTF in-process: false-positive collapse detected (2 consecutive), forcing full reset
```

**ASTF evaluation phases (per-trial verdict):**
```
(ASTF Phase 2: ignored counters per --astf-ignore-errors: {'err_cwf'})
(ASTF Phase 6: CPS rate info: target=86505 actual=86255 deviation=0.29%)
(ASTF evaluation complete: CPS=86255 active_flows=682807 error_pct=0.0857% retransmit_pct=13.3184% trial_result: pass)
```

### UDP/Mixed Protocol Tuning for OVS-DPDK

UDP and mixed-mode traffic require different tuning than pure TCP on OVS-DPDK
with conntrack. The key differences:

**`astf-max-flows` sizing:**

For UDP, set `astf-max-flows` to approximately `expected_NDR * 2`. UDP flows
don't close actively, so the flow table fills faster than TCP. Example:

```json
{ "arg": "astf-max-flows", "vals": ["100000"], "role": "client" }
```

Do NOT use the TCP default of 1,000,000 for UDP -- it will saturate and cause
CPS collapse without any error signal (only Phase 1c detects this).

**`astf-t-duration` for UDP:**

UDP has no FIN handshake, so teardown wait can be shorter:

```json
{ "arg": "astf-t-duration", "vals": ["5"], "role": "client" }
```

**Mixed mode with small UDP percentage:**

For mixed profiles where UDP is 1-10% of traffic, set a separate UDP drop
threshold to avoid penalizing the NDR based on minority traffic:

```json
{ "arg": "astf-max-udp-drop-pct", "vals": ["20"], "role": "client" },
{ "arg": "max-retries", "vals": ["2"], "role": "client" }
```

Without `astf-max-udp-drop-pct`, the default 5% error threshold applies to UDP
drops, which can reduce the mixed-mode NDR by 23% compared to the TCP-only NDR.
With the relaxed 20% UDP threshold, the search converges on the TCP retransmit
boundary (the majority traffic quality signal).

**Recommended profile parameters by protocol:**

| Parameter | TCP | UDP | Mixed (1% UDP) |
|-----------|-----|-----|----------------|
| `astf-max-flows` | 1000000 | **100000** | 1000000 |
| `astf-t-duration` | 10 | **5** | 10 |
| `astf-ramp-time` | 10 | **5** | 10 |
| `astf-max-retransmit-pct` | 20.0 | (not used) | 20.0 |
| `astf-max-udp-drop-pct` | (not used) | 5.0 (default) | **20.0** |
| `astf-max-cps-deviation-pct` | 50 (default) | **50** | 50 (default) |
| `max-retries` | 1 (default) | 1 (default) | **2** |
| `rate` (starting ceiling) | 500000 | **200000** | 500000 |

## Troubleshooting

### Roadblock Heartbeat Timeout (RC=5)

**Symptom**: Test aborts with `Failed ending current heartbeat monitoring
period -> heartbeat timeout` and exit code RC=5. Typically occurs during
longer trials (60s+) on OVS-DPDK compute hosts under high CPU load.

**Root cause**: The compute host's `nf_conntrack_tcp_timeout_established`
is set too low (e.g., 30s). During a 60-second ASTF trial, infrastructure
TCP connections (Crucible's Redis-based roadblock heartbeats between
controller and follower agents) sit idle while the DUT processes high-CPS
traffic. The kernel conntrack entry for these TCP connections expires after
30s. If the host runs nftables with `INPUT policy drop`, the expired entry
causes nftables to drop the heartbeat response packets as untracked "new"
connections that match no INPUT rule.

**Chain of events**:
1. ASTF trial starts (60s measurement)
2. High CPS traffic consumes OVS-DPDK PMD threads and CPU
3. Redis heartbeat connection sits idle for >30s
4. Kernel conntrack entry expires (`tcp_established=30`)
5. nftables `INPUT policy drop` blocks the heartbeat response
6. Roadblock detects heartbeat timeout, aborts with RC=5

**Fix**:

```bash
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=120
```

This keeps infrastructure TCP connections tracked through the longest
typical trial duration. See "Kernel Conntrack Timeout Tuning" for details.

### Connection Error Rate Too High

- Reduce `--rate` starting point or `--min-rate`
- Reduce `--astf-max-flows` to stay within conntrack table limits
- Verify DUT conntrack timeouts are tuned (see DUT Requirements section)
- Check DUT conntrack usage: `ovs-appctl dpctl/ct-get-nconns`
- Check DUT conntrack limit: `ovs-appctl dpctl/ct-get-maxconns`

### TRex Fails to Start in ASTF Mode

- Verify `--traffic-generator=trex-astf` is set (trafficgen-infra adds `--astf` automatically)
- Check `trex-server-stderrout.txt` in the sample directory
- Verify TRex is installed: `ls /opt/trex/`
- Verify TRex started correctly: check `trex-server-stderrout.txt` for library errors

### CPS Not Stabilizing (Ramp-Up Issues)

- Increase `--astf-ramp-time` (try 15-30 for long-lived profiles)
- Reduce `--astf-max-flows` to match DUT capacity

### SR-IOV VF Issues

- Always use `--no-promisc=ON` for VFs
- Use `--trex-software-mode=on` if hardware flow stats cause issues
- PCI device: `--trex-devices=VAR:PCIDEVICE_OPENSHIFT_IO_DPDK_NIC_1,...`

### Zero Connections (Phase 1 Abort)

- Verify MACs in `trex_cfg.yaml` are correct (check `trafficgen-infra-stderrout.txt`)
- Verify IP ranges don't conflict with DUT routing
- Check that TRex ports are bound to VFIO: `dpdk_setup_ports.py -t`

### OVS-DPDK: No Traffic Reaching VM

- Verify `--dst-macs` is set with the VM's Virtio NIC MACs
- Verify `--testpmd-dst-macs` is set with TRex port MACs
- Verify `testpmd-forward-mode=mac` (enables `--eth-peer` in testpmd)
- Check OVS vhost port status: `ovs-vsctl list interface <vhu-port> | grep status`
  should show `status=connected` when testpmd is running
- Check OVS PMD utilization: `ovs-appctl dpif-netdev/pmd-rxq-show`

### OVS-DPDK: Phase 2 Catastrophic Errors

- `err_cwf` (client pkt without flow): packets arriving at wrong TRex port.
  Check MAC mapping between TRex ports and VM Virtio ports.
- `err_flow_overflow`: TRex flow table full. Increase `--astf-max-flows`.
- `err_s_nf_throttled`: server new flow throttled. Reduce `--rate`.

If `err_cwf` is expected in your topology (OVS-DPDK + testpmd mac-fwd),
use `--astf-ignore-errors` to prevent hard-fail:

```json
{ "arg": "astf-ignore-errors", "vals": ["err_cwf"], "role": "client" }
```

Verify connections are still completing (check `connection_error_pct` = 0%)
before ignoring this counter. If `connection_error_pct` is non-zero alongside
`err_cwf`, there is a real routing problem -- do not ignore.

### OVS-DPDK: Kernel Conntrack Tuning

Ensure kernel conntrack timeouts on the compute host are tuned. Default
kernel timeouts (e.g., `tcp_established=432000`) cause zombie conntrack
entries that exhaust the table:

```bash
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=120
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=1
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_fin_wait=1
sysctl -w net.netfilter.nf_conntrack_max=10000000
```

See "Kernel Conntrack Timeout Tuning" in the DUT Setup Reference for the
full explanation of why 120s (not 30s) is required.

## External ASTF Profile Format

Create a `.py` file with this structure:

```python
from trex.astf.api import *
import argparse

class Prof1():
    def get_profile(self, tunables=[], **kwargs):
        parser = argparse.ArgumentParser()
        parser.add_argument('--my-param', type=int, default=64)
        args = parser.parse_args(tunables)

        prog_c = ASTFProgram(stream=True)  # TCP
        prog_c.send(b'x' * args.my_param)
        prog_c.recv(args.my_param)

        prog_s = ASTFProgram(stream=True)
        prog_s.recv(args.my_param)
        prog_s.send(b'y' * args.my_param)

        ip_gen = ASTFIPGen(
            glob=ASTFIPGenGlobal(ip_offset="1.0.0.0"),
            dist_client=ASTFIPGenDist(ip_range=["16.0.0.0","16.0.255.255"],
                                      distribution="seq"),
            dist_server=ASTFIPGenDist(ip_range=["48.0.0.0","48.0.255.255"],
                                      distribution="seq")
        )

        return ASTFProfile(
            default_ip_gen=ip_gen,
            templates=ASTFTemplate(
                client_template=ASTFTCPClientTemplate(
                    program=prog_c, ip_gen=ip_gen, cps=100, cont=True),
                server_template=ASTFTCPServerTemplate(program=prog_s)
            )
        )

def register():
    return Prof1()
```

Pass to binary search with: `--astf-profile=/path/to/my-profile.py`

## See Also

- [README-binary-search.md](README-binary-search.md) -- binary search algorithm documentation
- [astf-profiles/](astf-profiles/) -- ready-to-use NFV scenario profiles
- [TRex ASTF Documentation](https://trex-tgn.cisco.com/trex/doc/trex_astf.html)
- [OVS Conntrack Benchmarking](https://people.redhat.com/~rjarry/posts/conntrack-benchmarking/) -- methodology reference
