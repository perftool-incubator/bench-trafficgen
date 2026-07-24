# Grout DPDK L3 Integration — User Guide

**Version:** 1.0
**Branch:** `grout-l3-to-main` (bench-trafficgen)
**Grout Version:** v0.16.0 (DPDK 25.11.2)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Reference Architecture](#2-reference-architecture)
3. [Prerequisites](#3-prerequisites)
4. [Parameter Reference](#4-parameter-reference)
5. [Auto-Discovery Messaging Flow](#5-auto-discovery-messaging-flow)
6. [Run File Configuration Guide](#6-run-file-configuration-guide)
   - 6.1 [Minimal STL Single Port-Pair](#61-minimal-stl-single-port-pair)
   - 6.2 [ASTF Single Port-Pair](#62-astf-single-port-pair)
   - 6.3 [STL Multi-Port (4 Port-Pairs)](#63-stl-multi-port-4-port-pairs)
   - 6.4 [ASTF Multi-Port (4 Port-Pairs)](#64-astf-multi-port-4-port-pairs)
   - 6.5 [IPv6 STL Single Port-Pair](#65-ipv6-stl-single-port-pair)
7. [IP Addressing and Subnet Design](#7-ip-addressing-and-subnet-design)
8. [CPU Affinity Configuration](#8-cpu-affinity-configuration)
9. [Data Collection and Observability](#9-data-collection-and-observability)
10. [Grout Version Management](#10-grout-version-management)
11. [Troubleshooting](#11-troubleshooting)
12. [Known Issues and Limitations](#12-known-issues-and-limitations)

---

## 1. Overview

Grout is a DPDK-based L3 graph router that replaces testpmd as the server-side DUT
in bench-trafficgen. Where testpmd operates at L2 (MAC forwarding), Grout performs
full IPv4/IPv6 routing with ARP/NDP resolution, FIB lookup, and nexthop forwarding.

**Supported TRex backends:**

| Backend | Mode | Protocol | Use Case |
|---------|------|----------|----------|
| `trex-txrx` | STL (Stateless) | UDP/TCP | Throughput (pps/bps), packet loss |
| `trex-txrx-profile` | STL (Profile) | UDP/TCP | Custom traffic profiles |
| `trex-astf` | ASTF (Stateful) | TCP/UDP | CPS, connection tracking, L4 workloads |

**Supported `switch-type` values:**

| Value | DUT | Layer | Description |
|-------|-----|-------|-------------|
| `null` | None | — | No DUT, direct loopback |
| `testpmd` | DPDK testpmd | L2 | MAC-based forwarding (existing) |
| `grout` | Grout DPDK router | L3 | IPv4/IPv6 routing with ARP/NDP/FIB (new) |

---

## 2. Reference Architecture

### 2.1 Single Port-Pair Topology

```
┌─────────────────────────────────────┐
│          Client Host                │
│  ┌──────────────────────────┐       │
│  │  TRex (trex-txrx/astf)   │       │
│  │  Port 0      Port 1      │       │
│  │  10.0.0.100  10.0.1.100  │       │
│  └─────┬────────────┬───────┘       │
│        │            │               │
└────────┼────────────┼───────────────┘
         │ PCI        │ PCI
    ┌────┴────────────┴────┐
    │     Physical/        │
    │   Virtual Switch     │
    │   (cable/OVS-DPDK)   │
    └────┬────────────┬────┘
         │            │
┌────────┼────────────┼───────────────┐
│  ┌─────┴────────────┴──────┐        │
│  │      Grout Router       │        │
│  │  p0: 10.0.0.1/24        │        │
│  │  p1: 10.0.1.1/24        │        │
│  │                         │        │
│  │  Route: 10.0.0.0/24→p0  │        │
│  │  Route: 10.0.1.0/24→p1  │        │
│  └─────────────────────────┘        │
│          Server Host                │
└─────────────────────────────────────┘
```

**Traffic flow (STL):**
1. TRex Port 0 sends packet: `src=10.0.0.100 → dst=10.0.1.100`
2. Grout p0 receives, FIB lookup: `10.0.1.0/24 → p1`
3. Nexthop resolves TRex Port 1 MAC via static entry
4. Grout forwards out p1 → TRex Port 1 receives

**Traffic flow (ASTF):**
1. TRex Port 0 sends TCP SYN: `src=10.0.0.100 → dst=10.0.1.100`
2. Grout p0 receives, routes to p1 via nexthop
3. TRex Port 1 receives SYN, responds with SYN-ACK
4. Grout p1 receives SYN-ACK, routes back to p0 via nexthop
5. Full TCP session established through Grout

### 2.2 Multi-Port-Pair Topology (4 pairs, 8 ports)

```
┌──────────────────────────────────────────────────────┐
│                    Client Host                       │
│  ┌────────────────────────────────────────────┐      │
│  │                  TRex                      │      │
│  │  P0         P1         P2  ...  P6    P7   │      │
│  │  10.0.0.100 10.0.1.100 10.0.2.100  10.0.7  │      │
│  └──┬──────────┬──────────┬────────────┬──────┘      │
└─────┼──────────┼──────────┼────────────┼─────────────┘
      │          │          │            │
┌─────┼──────────┼──────────┼────────────┼─────────────┐
│  ┌──┴──────────┴──────────┴────────────┴──────┐      │
│  │              Grout Router                  │      │
│  │  p0: 10.0.0.1/24    p1: 10.0.1.1/24        │      │
│  │  p2: 10.0.2.1/24    p3: 10.0.3.1/24        │      │
│  │  p4: 10.0.4.1/24    p5: 10.0.5.1/24        │      │
│  │  p6: 10.0.6.1/24    p7: 10.0.7.1/24        │      │
│  └────────────────────────────────────────────┘      │
│                    Server Host                       │
└──────────────────────────────────────────────────────┘
```

Port pairing follows `device-pairs=0:1,2:3,4:5,6:7`:
- Port pair 0: P0 (client, 10.0.0.x) ↔ P1 (server, 10.0.1.x) via Grout p0/p1
- Port pair 1: P2 (client, 10.0.2.x) ↔ P3 (server, 10.0.3.x) via Grout p2/p3
- etc.

---

## 3. Prerequisites

### 3.1 Host Requirements

| Requirement | Client Host | Server Host |
|-------------|-------------|-------------|
| **UserEnv** | `alma9` | `alma10` (glibc 2.38+ required by Grout) |
| **DPDK driver** | `vfio-pci` | `vfio-pci` |
| **Hugepages** | 1GB pages recommended | 1GB pages recommended |
| **IOMMU** | Enabled | Enabled |
| **IPv6** | Optional | Must NOT be disabled in kernel (`ipv6.disable=0`) |

### 3.2 Engine ID Alignment

Both client and server engines **must** use matching IDs for auto-discovery to work:

```json
"engines": [{ "role": "client", "ids": "1" }]
"engines": [{ "role": "server", "ids": "1" }]
```

The top-level `benchmarks.ids` must also match (e.g. `"1"`).

### 3.3 PCI Device Requirements

- Server devices must be an **even number** (port pairs)
- Client devices must match the count of server devices
- Devices must be bound to `vfio-pci` driver before the test

---

## 4. Parameter Reference

### 4.1 Server-Role Parameters (Grout)

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `switch-type` | Yes | — | Must be `"grout"` |
| `grout-ip-addrs` | Yes | — | Comma-separated CIDRs, one per port. Example: `"10.0.0.1/24,10.0.1.1/24"` |
| `server-devices` | Yes | — | Comma-separated PCI addresses for Grout ports |
| `grout-forward-mode` | No | `"ipv4"` | Forwarding mode: `ipv4`, `ipv6`, `bridge` |
| `grout-rxqs` | No | `"1"` | RX queues per port (keep at 1 for virtio-net) |
| `grout-qsize` | No | `"2048"` | Queue descriptor ring size |
| `grout-datapath-cpus` | No | — | CPU list for datapath threads (e.g. `"6,7,8,9"`) |
| `grout-control-cpus` | No | — | CPU list for control thread (e.g. `"4,5"`) |
| `grout-routes` | No | — | Additional static routes (comma-separated) |
| `grout-static-arp` | No | — | Manual nexthop entries (overrides auto-discovery). Format: `"iface/ip/mac;iface/ip/mac"` |
| `grout-version` | No | — | Request specific Grout version (e.g. `"v0.16.0"`). Downloads if different from bundled. |

### 4.2 Client-Role Parameters (TRex)

Standard TRex parameters apply. Key Grout-relevant ones:

| Parameter | Notes for Grout |
|-----------|-----------------|
| `traffic-generator` | `trex-txrx` (STL) or `trex-astf` (ASTF) |
| `trex-config` | Custom `trex_cfg.yaml` with L3 `port_info` (ip + default_gw). Required for ASTF. |
| `trex-devices` | Must match server port count |
| `src-ips` | Source IPs matching Grout subnets. Enables IP info in auto-discovery for nexthop generation. Accepts IPv4 and IPv6. |
| `dst-ips` | (STL only) Destination IPs — cross-matched to port pairs |
| `dst-macs` | **Auto-collected** from Grout. No need to set manually. |
| `astf-ip-offset` | (ASTF only) IP offset per port pair. Use `"0.0.2.0"` for multi-port. |
| `astf-client-ip-start/end` | (ASTF only) Client IP range within port-pair 0's subnet |
| `astf-server-ip-start/end` | (ASTF only) Server IP range within port-pair 0's subnet |

### 4.3 Parameter Validation (multiplex.json)

| Validation Key | Arguments | Pattern |
|----------------|-----------|---------|
| `switch_types` | `switch-type` | `^(null\|testpmd\|grout)$` |
| `grout_forward_mode` | `grout-forward-mode` | `^(ipv4\|ipv6\|bridge)$` |
| `grout_ip_config` | `grout-ip-addrs`, `grout-routes` | `^.+$` |
| `grout_positive_integer` | `grout-rxqs`, `grout-qsize` | `^[1-9][0-9]*$` |
| `grout_cpu_list` | `grout-datapath-cpus`, `grout-control-cpus` | CPU list/range regex |
| `grout_static_arp` | `grout-static-arp` | `^.+$` |
| `grout_version` | `grout-version` | `^v[0-9]+\.[0-9]+\.[0-9]+$` |

---

## 5. Auto-Discovery Messaging Flow

Grout L3 uses Rickshaw's roadblock messaging system to automatically exchange MAC
addresses between TRex (client) and Grout (server), eliminating manual `dst-macs`
and `grout-static-arp` configuration.

```
  Phase              Client (TRex)                Server (Grout)
  ─────              ─────────────                ──────────────
  infra-start-end    Collect TRex port MACs  ───►  (receives via msgs/rx)
                     Write to msgs/tx/macs         Read infra message
                                                   Auto-generate nexthops
                                                   Add gateway routes

  server-start-end   (receives via msgs/rx)  ◄───  Collect Grout port MACs
                     Read svc message              Write to msgs/tx/svc
                     Override --dst-macs

  client-start-end   Use auto-collected            (waiting)
                     dst-macs for traffic
```

**What gets auto-collected:**

| Direction | Data | Purpose |
|-----------|------|---------|
| Client → Server | TRex port MACs (+ optional IPs) | Grout creates static nexthop + gateway route per port |
| Server → Client | Grout port MACs | TRex uses as `--dst-macs` for L3 forwarding |

**Requirements for auto-discovery:**
- Engine IDs must match (both `"1"`, or both `"1-2"`, etc.)
- The `engine-script-library` must not have the `local cs_buddy=""` shadowing bug (fixed on current install)

---

## 6. Run File Configuration Guide

### 6.1 Minimal STL Single Port-Pair

**Scenario:** Basic L3 forwarding validation with UDP traffic through Grout.

```json
{
  "benchmarks": [
    {
      "name": "trafficgen",
      "ids": "1",
      "mv-params": {
        "global-options": [
          {
            "name": "global",
            "params": [
              { "arg": "switch-type", "vals": ["grout"], "role": "server" },
              { "arg": "grout-ip-addrs", "vals": ["10.0.0.1/24,10.0.1.1/24"], "role": "server" },
              { "arg": "server-devices", "vals": ["<SERVER_PCI_0>,<SERVER_PCI_1>"], "role": "server" }
            ]
          }
        ],
        "sets": [
          {
            "include": "global",
            "params": [
              { "arg": "traffic-generator", "vals": ["trex-txrx"], "role": "client" },
              { "arg": "trex-devices", "vals": ["<CLIENT_PCI_0>,<CLIENT_PCI_1>"], "role": "client" },
              { "arg": "trex-active-devices", "vals": ["<CLIENT_PCI_0>,<CLIENT_PCI_1>"], "role": "client" },
              { "arg": "src-ips", "vals": ["10.0.0.100,10.0.1.100"], "role": "client" },
              { "arg": "dst-ips", "vals": ["10.0.1.100,10.0.0.100"], "role": "client" },
              { "arg": "num-flows", "vals": ["2"], "role": "client" },
              { "arg": "packet-protocol", "vals": ["UDP"], "role": "client" },
              { "arg": "frame-size", "vals": ["64"], "role": "client" },
              { "arg": "rate-unit", "vals": ["%"], "role": "client" },
              { "arg": "rate", "vals": ["10"], "role": "client" },
              { "arg": "one-shot", "vals": ["0"], "role": "client" },
              { "arg": "search-runtime", "vals": ["30"], "role": "client" },
              { "arg": "validation-runtime", "vals": ["30"], "role": "client" },
              { "arg": "traffic-direction", "vals": ["unidirectional"], "role": "client" },
              { "arg": "use-src-ip-flows", "vals": ["1"], "role": "client" },
              { "arg": "use-dst-ip-flows", "vals": ["1"], "role": "client" },
              { "arg": "use-device-stats", "vals": ["ON"], "role": "client" },
              { "arg": "max-loss-pct", "vals": ["1"], "role": "client" },
              { "arg": "warmup-trial", "vals": ["ON"], "role": "client" },
              { "arg": "send-teaching-warmup", "vals": ["ON"], "role": "client" },
              { "arg": "teaching-warmup-packet-type", "vals": ["garp"], "role": "client" }
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
          "engines": [{ "role": "client", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma9", "cpu-partitioning": true
            },
            "host": "<CLIENT_HOSTNAME>"
          }
        },
        {
          "engines": [{ "role": "server", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma10", "cpu-partitioning": true
            },
            "host": "<SERVER_HOSTNAME>"
          }
        }
      ]
    }
  ],
  "run-params": { "num-samples": 1, "max-sample-failures": 1 },
  "tags": { "scenario": "grout-l3-stl-basic", "dut_type": "grout" },
  "tool-params": []
}
```

**Key points:**
- `src-ips` and `dst-ips` are cross-matched for bidirectional routing through Grout
- No `dst-macs` or `grout-static-arp` needed — auto-discovery handles both
- Server `userenv` must be `alma10`; client `userenv` must be `alma9`

---

### 6.2 ASTF Single Port-Pair

**Scenario:** TCP connection-per-second testing through Grout with short-lived connections.

Requires a custom `trex_cfg.yaml` with L3 port_info:

**`grout-trex_cfg.yaml`** (place alongside the runfile):
```yaml
- c: 2
  interfaces:
  - <CLIENT_PCI_0>
  - <CLIENT_PCI_1>
  limit_memory: 2048
  port_bandwidth_gb: 25
  port_info:
  - default_gw: 10.0.0.1
    ip: 10.0.0.100
  - default_gw: 10.0.1.1
    ip: 10.0.1.100
  version: 2
```

**Run file:**
```json
{
  "benchmarks": [
    {
      "name": "trafficgen",
      "ids": "1",
      "mv-params": {
        "global-options": [
          {
            "name": "global",
            "params": [
              { "arg": "switch-type", "vals": ["grout"], "role": "server" },
              { "arg": "grout-ip-addrs", "vals": ["10.0.0.1/24,10.0.1.1/24"], "role": "server" },
              { "arg": "server-devices", "vals": ["<SERVER_PCI_0>,<SERVER_PCI_1>"], "role": "server" }
            ]
          }
        ],
        "sets": [
          {
            "include": "global",
            "params": [
              { "arg": "traffic-generator", "vals": ["trex-astf"], "role": "client" },
              { "arg": "trex-config", "vals": ["grout-trex_cfg.yaml"], "role": "client" },
              { "arg": "trex-devices", "vals": ["<CLIENT_PCI_0>,<CLIENT_PCI_1>"], "role": "client" },
              { "arg": "trex-active-devices", "vals": ["<CLIENT_PCI_0>,<CLIENT_PCI_1>"], "role": "client" },
              { "arg": "astf-protocol", "vals": ["tcp"], "role": "client" },
              { "arg": "astf-message-size", "vals": ["20"], "role": "client" },
              { "arg": "astf-num-messages", "vals": ["1"], "role": "client" },
              { "arg": "astf-tcp-mss", "vals": ["1460"], "role": "client" },
              { "arg": "astf-client-ip-start", "vals": ["10.0.0.100"], "role": "client" },
              { "arg": "astf-client-ip-end", "vals": ["10.0.0.200"], "role": "client" },
              { "arg": "astf-server-ip-start", "vals": ["10.0.1.100"], "role": "client" },
              { "arg": "astf-server-ip-end", "vals": ["10.0.1.200"], "role": "client" },
              { "arg": "astf-max-flows", "vals": ["10000"], "role": "client" },
              { "arg": "astf-ramp-time", "vals": ["5"], "role": "client" },
              { "arg": "astf-max-error-pct", "vals": ["5.0"], "role": "client" },
              { "arg": "astf-max-retransmit-pct", "vals": ["10.0"], "role": "client" },
              { "arg": "astf-t-duration", "vals": ["30"], "role": "client" },
              { "arg": "astf-ignore-errors", "vals": ["err_cwf,err_no_syn"], "role": "client" },
              { "arg": "rate-unit", "vals": ["cps"], "role": "client" },
              { "arg": "rate", "vals": ["100000"], "role": "client" },
              { "arg": "one-shot", "vals": ["0"], "role": "client" },
              { "arg": "search-runtime", "vals": ["30"], "role": "client" },
              { "arg": "validation-runtime", "vals": ["30"], "role": "client" },
              { "arg": "rate-tolerance-failure", "vals": ["fail"], "role": "client" }
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
          "engines": [{ "role": "client", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma9", "cpu-partitioning": true
            },
            "host": "<CLIENT_HOSTNAME>"
          }
        },
        {
          "engines": [{ "role": "server", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma10", "cpu-partitioning": true
            },
            "host": "<SERVER_HOSTNAME>"
          }
        }
      ]
    }
  ],
  "run-params": { "num-samples": 1, "max-sample-failures": 1 },
  "tags": { "scenario": "grout-l3-astf-tcp", "dut_type": "grout" },
  "tool-params": []
}
```

**Key points:**
- ASTF requires a custom `trex_cfg.yaml` with `port_info` containing `ip` and `default_gw`
- `default_gw` must point to Grout's interface IP for that subnet
- Do NOT set `astf-ip-offset` for single port-pair (default `0.0.0.0` is correct)
- Gateway routes are auto-added so the entire IP range (100–200) is covered

---

### 6.3 STL Multi-Port (4 Port-Pairs)

**Scenario:** High-throughput L3 forwarding with 8 ports across 4 port-pairs.

```json
{
  "benchmarks": [
    {
      "name": "trafficgen",
      "ids": "1",
      "mv-params": {
        "global-options": [
          {
            "name": "global",
            "params": [
              { "arg": "switch-type", "vals": ["grout"], "role": "server" },
              { "arg": "grout-ip-addrs", "vals": ["10.0.0.1/24,10.0.1.1/24,10.0.2.1/24,10.0.3.1/24,10.0.4.1/24,10.0.5.1/24,10.0.6.1/24,10.0.7.1/24"], "role": "server" },
              { "arg": "grout-datapath-cpus", "vals": ["6,7,8,9"], "role": "server" },
              { "arg": "grout-control-cpus", "vals": ["4,5"], "role": "server" },
              { "arg": "grout-rxqs", "vals": ["1"], "role": "server" },
              { "arg": "grout-qsize", "vals": ["2048"], "role": "server" },
              { "arg": "server-devices", "vals": ["<S_PCI_0>,<S_PCI_1>,<S_PCI_2>,<S_PCI_3>,<S_PCI_4>,<S_PCI_5>,<S_PCI_6>,<S_PCI_7>"], "role": "server" }
            ]
          }
        ],
        "sets": [
          {
            "include": "global",
            "params": [
              { "arg": "traffic-generator", "vals": ["trex-txrx"], "role": "client" },
              { "arg": "trex-devices", "vals": ["<C_PCI_0>,<C_PCI_1>,<C_PCI_2>,<C_PCI_3>,<C_PCI_4>,<C_PCI_5>,<C_PCI_6>,<C_PCI_7>"], "role": "client" },
              { "arg": "trex-active-devices", "vals": ["<C_PCI_0>,<C_PCI_1>,<C_PCI_2>,<C_PCI_3>,<C_PCI_4>,<C_PCI_5>,<C_PCI_6>,<C_PCI_7>"], "role": "client" },
              { "arg": "trex-mem-limit", "vals": ["32768"], "role": "client" },
              { "arg": "src-ips", "vals": ["10.0.0.100,10.0.1.100,10.0.2.100,10.0.3.100,10.0.4.100,10.0.5.100,10.0.6.100,10.0.7.100"], "role": "client" },
              { "arg": "dst-ips", "vals": ["10.0.1.100,10.0.0.100,10.0.3.100,10.0.2.100,10.0.5.100,10.0.4.100,10.0.7.100,10.0.6.100"], "role": "client" },
              { "arg": "num-flows", "vals": ["1024"], "role": "client" },
              { "arg": "packet-protocol", "vals": ["UDP"], "role": "client" },
              { "arg": "frame-size", "vals": ["64"], "role": "client" },
              { "arg": "rate-unit", "vals": ["%"], "role": "client" },
              { "arg": "rate", "vals": ["100"], "role": "client" },
              { "arg": "one-shot", "vals": ["0"], "role": "client" },
              { "arg": "search-runtime", "vals": ["30"], "role": "client" },
              { "arg": "validation-runtime", "vals": ["60"], "role": "client" },
              { "arg": "traffic-direction", "vals": ["bidirectional"], "role": "client" },
              { "arg": "use-src-port-flows", "vals": ["1"], "role": "client" },
              { "arg": "use-dst-port-flows", "vals": ["1"], "role": "client" },
              { "arg": "use-device-stats", "vals": ["ON"], "role": "client" },
              { "arg": "max-loss-pct", "vals": ["5"], "role": "client" },
              { "arg": "warmup-trial", "vals": ["ON"], "role": "client" },
              { "arg": "send-teaching-warmup", "vals": ["ON"], "role": "client" },
              { "arg": "teaching-warmup-packet-type", "vals": ["garp"], "role": "client" }
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
          "engines": [{ "role": "client", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma9", "cpu-partitioning": true
            },
            "host": "<CLIENT_HOSTNAME>"
          }
        },
        {
          "engines": [{ "role": "server", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma10", "cpu-partitioning": true
            },
            "host": "<SERVER_HOSTNAME>"
          }
        }
      ]
    }
  ],
  "run-params": { "num-samples": 1, "max-sample-failures": 1 },
  "tags": { "scenario": "grout-l3-stl-multiport", "dut_type": "grout" },
  "tool-params": []
}
```

**Key points:**
- `dst-ips` must cross-reference port pairs: port 0→port 1's subnet, port 1→port 0's subnet, etc.
- `grout-datapath-cpus` and `grout-control-cpus` are recommended for multi-port to avoid contention
- `trex-mem-limit` should be increased (32768 MB) for 8-port configs

---

### 6.4 ASTF Multi-Port (4 Port-Pairs)

**Scenario:** TCP CPS testing across 4 port-pairs with IP offset for subnet separation.

Requires a custom `trex_cfg.yaml`:

**`grout-vm-trex_cfg.yaml`:**
```yaml
- c: 4
  interfaces:
  - <C_PCI_0>
  - <C_PCI_1>
  - <C_PCI_2>
  - <C_PCI_3>
  - <C_PCI_4>
  - <C_PCI_5>
  - <C_PCI_6>
  - <C_PCI_7>
  limit_memory: 32768
  port_bandwidth_gb: 25
  port_info:
  - { ip: 10.0.0.100, default_gw: 10.0.0.1 }
  - { ip: 10.0.1.100, default_gw: 10.0.1.1 }
  - { ip: 10.0.2.100, default_gw: 10.0.2.1 }
  - { ip: 10.0.3.100, default_gw: 10.0.3.1 }
  - { ip: 10.0.4.100, default_gw: 10.0.4.1 }
  - { ip: 10.0.5.100, default_gw: 10.0.5.1 }
  - { ip: 10.0.6.100, default_gw: 10.0.6.1 }
  - { ip: 10.0.7.100, default_gw: 10.0.7.1 }
  version: 2
```

**Run file:**
```json
{
  "benchmarks": [
    {
      "name": "trafficgen",
      "ids": "1",
      "mv-params": {
        "global-options": [
          {
            "name": "global",
            "params": [
              { "arg": "switch-type", "vals": ["grout"], "role": "server" },
              { "arg": "grout-ip-addrs", "vals": ["10.0.0.1/24,10.0.1.1/24,10.0.2.1/24,10.0.3.1/24,10.0.4.1/24,10.0.5.1/24,10.0.6.1/24,10.0.7.1/24"], "role": "server" },
              { "arg": "grout-datapath-cpus", "vals": ["6,7,8,9"], "role": "server" },
              { "arg": "grout-control-cpus", "vals": ["4,5"], "role": "server" },
              { "arg": "grout-rxqs", "vals": ["1"], "role": "server" },
              { "arg": "grout-qsize", "vals": ["2048"], "role": "server" },
              { "arg": "server-devices", "vals": ["<S_PCI_0>,<S_PCI_1>,<S_PCI_2>,<S_PCI_3>,<S_PCI_4>,<S_PCI_5>,<S_PCI_6>,<S_PCI_7>"], "role": "server" }
            ]
          }
        ],
        "sets": [
          {
            "include": "global",
            "params": [
              { "arg": "traffic-generator", "vals": ["trex-astf"], "role": "client" },
              { "arg": "trex-config", "vals": ["grout-vm-trex_cfg.yaml"], "role": "client" },
              { "arg": "trex-devices", "vals": ["<C_PCI_0>,<C_PCI_1>,<C_PCI_2>,<C_PCI_3>,<C_PCI_4>,<C_PCI_5>,<C_PCI_6>,<C_PCI_7>"], "role": "client" },
              { "arg": "trex-active-devices", "vals": ["<C_PCI_0>,<C_PCI_1>,<C_PCI_2>,<C_PCI_3>,<C_PCI_4>,<C_PCI_5>,<C_PCI_6>,<C_PCI_7>"], "role": "client" },
              { "arg": "trex-mem-limit", "vals": ["32768"], "role": "client" },
              { "arg": "astf-protocol", "vals": ["tcp"], "role": "client" },
              { "arg": "astf-message-size", "vals": ["20"], "role": "client" },
              { "arg": "astf-num-messages", "vals": ["1"], "role": "client" },
              { "arg": "astf-tcp-mss", "vals": ["1460"], "role": "client" },
              { "arg": "astf-client-ip-start", "vals": ["10.0.0.100"], "role": "client" },
              { "arg": "astf-client-ip-end", "vals": ["10.0.0.200"], "role": "client" },
              { "arg": "astf-server-ip-start", "vals": ["10.0.1.100"], "role": "client" },
              { "arg": "astf-server-ip-end", "vals": ["10.0.1.200"], "role": "client" },
              { "arg": "astf-ip-offset", "vals": ["0.0.2.0"], "role": "client" },
              { "arg": "astf-max-flows", "vals": ["10000"], "role": "client" },
              { "arg": "astf-ramp-time", "vals": ["5"], "role": "client" },
              { "arg": "astf-max-error-pct", "vals": ["5.0"], "role": "client" },
              { "arg": "astf-max-retransmit-pct", "vals": ["10.0"], "role": "client" },
              { "arg": "astf-t-duration", "vals": ["30"], "role": "client" },
              { "arg": "astf-ignore-errors", "vals": ["err_cwf,err_no_syn"], "role": "client" },
              { "arg": "astf-per-core-distribution", "vals": ["seq"], "role": "client" },
              { "arg": "rate-unit", "vals": ["cps"], "role": "client" },
              { "arg": "rate", "vals": ["100000"], "role": "client" },
              { "arg": "one-shot", "vals": ["0"], "role": "client" },
              { "arg": "search-runtime", "vals": ["30"], "role": "client" },
              { "arg": "validation-runtime", "vals": ["30"], "role": "client" },
              { "arg": "rate-tolerance-failure", "vals": ["fail"], "role": "client" }
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
          "engines": [{ "role": "client", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma9", "cpu-partitioning": true
            },
            "host": "<CLIENT_HOSTNAME>"
          }
        },
        {
          "engines": [{ "role": "server", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma10", "cpu-partitioning": true
            },
            "host": "<SERVER_HOSTNAME>"
          }
        }
      ]
    }
  ],
  "run-params": { "num-samples": 1, "max-sample-failures": 1 },
  "tags": { "scenario": "grout-l3-astf-multiport", "dut_type": "grout" },
  "tool-params": []
}
```

**Critical ASTF multi-port settings:**
- `astf-ip-offset` must be `"0.0.2.0"` to align IP ranges with Grout subnets
- Each port pair gets its own subnet: pair 0 uses 10.0.0.x/10.0.1.x, pair 1 uses 10.0.2.x/10.0.3.x, etc.
- `trex_cfg.yaml` `port_info` must list IPs and gateways for ALL ports

---

### 6.5 IPv6 STL Single Port-Pair

**Scenario:** IPv6 L3 forwarding validation with UDP traffic through Grout.

```json
{
  "benchmarks": [
    {
      "name": "trafficgen",
      "ids": "1",
      "mv-params": {
        "global-options": [
          {
            "name": "global",
            "params": [
              { "arg": "switch-type", "vals": ["grout"], "role": "server" },
              { "arg": "grout-forward-mode", "vals": ["ipv6"], "role": "server" },
              { "arg": "grout-ip-addrs", "vals": ["fd00::1/64,fd00:1::1/64"], "role": "server" },
              { "arg": "server-devices", "vals": ["<SERVER_PCI_0>,<SERVER_PCI_1>"], "role": "server" }
            ]
          }
        ],
        "sets": [
          {
            "include": "global",
            "params": [
              { "arg": "traffic-generator", "vals": ["trex-txrx"], "role": "client" },
              { "arg": "trex-devices", "vals": ["<CLIENT_PCI_0>,<CLIENT_PCI_1>"], "role": "client" },
              { "arg": "trex-active-devices", "vals": ["<CLIENT_PCI_0>,<CLIENT_PCI_1>"], "role": "client" },
              { "arg": "src-ips", "vals": ["fd00::100,fd00:1::100"], "role": "client" },
              { "arg": "dst-ips", "vals": ["fd00:1::100,fd00::100"], "role": "client" },
              { "arg": "num-flows", "vals": ["2"], "role": "client" },
              { "arg": "packet-protocol", "vals": ["UDP"], "role": "client" },
              { "arg": "frame-size", "vals": ["64"], "role": "client" },
              { "arg": "rate-unit", "vals": ["%"], "role": "client" },
              { "arg": "rate", "vals": ["10"], "role": "client" },
              { "arg": "one-shot", "vals": ["0"], "role": "client" },
              { "arg": "search-runtime", "vals": ["30"], "role": "client" },
              { "arg": "validation-runtime", "vals": ["30"], "role": "client" },
              { "arg": "traffic-direction", "vals": ["unidirectional"], "role": "client" },
              { "arg": "use-src-ip-flows", "vals": ["1"], "role": "client" },
              { "arg": "use-dst-ip-flows", "vals": ["1"], "role": "client" },
              { "arg": "use-device-stats", "vals": ["ON"], "role": "client" },
              { "arg": "max-loss-pct", "vals": ["1"], "role": "client" },
              { "arg": "warmup-trial", "vals": ["ON"], "role": "client" },
              { "arg": "send-teaching-warmup", "vals": ["ON"], "role": "client" },
              { "arg": "teaching-warmup-packet-type", "vals": ["garp"], "role": "client" }
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
          "engines": [{ "role": "client", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma9", "cpu-partitioning": true
            },
            "host": "<CLIENT_HOSTNAME>"
          }
        },
        {
          "engines": [{ "role": "server", "ids": "1" }],
          "config": {
            "settings": {
              "osruntime": "chroot", "user": "root",
              "userenv": "alma10", "cpu-partitioning": true
            },
            "host": "<SERVER_HOSTNAME>"
          }
        }
      ]
    }
  ],
  "run-params": { "num-samples": 1, "max-sample-failures": 1 },
  "tags": { "scenario": "grout-l3-stl-ipv6", "dut_type": "grout" },
  "tool-params": []
}
```

**Key points:**
- `grout-forward-mode=ipv6` enables IPv6 routing on the server
- `grout-ip-addrs` uses IPv6 CIDR notation (e.g. `fd00::1/64`)
- `src-ips` and `dst-ips` use IPv6 addresses matching the Grout subnets
- IPv6 must NOT be disabled in the server kernel (`ipv6.disable=0`)
- For IPv6 ASTF, additionally set `astf-ipv6=ON` on the client — see `README-trex-astf.md` for ASTF IPv6 parameters

---

## 7. IP Addressing and Subnet Design

### 7.1 Subnet Layout Rules

Each Grout port gets a unique `/24` subnet. Port pairs share adjacent subnets:

| Port Pair | Even Port (client dir) | Odd Port (server dir) |
|-----------|----------------------|---------------------|
| 0 | p0: 10.0.0.1/24 | p1: 10.0.1.1/24 |
| 1 | p2: 10.0.2.1/24 | p3: 10.0.3.1/24 |
| 2 | p4: 10.0.4.1/24 | p5: 10.0.5.1/24 |
| 3 | p6: 10.0.6.1/24 | p7: 10.0.7.1/24 |

### 7.2 ASTF `astf-ip-offset` Explained

The offset determines how IP ranges shift per port pair:

| Offset | Port Pair 0 Client IPs | Port Pair 1 Client IPs | Port Pair 2 Client IPs |
|--------|----------------------|----------------------|----------------------|
| `0.0.0.0` | 10.0.0.100–200 | 10.0.0.100–200 (COLLISION!) | 10.0.0.100–200 |
| `1.0.0.0` | 10.0.0.100–200 | 11.0.0.100–200 (wrong subnet!) | 12.0.0.100–200 |
| **`0.0.2.0`** | **10.0.0.100–200** | **10.0.2.100–200** | **10.0.4.100–200** |

**Always use `astf-ip-offset=0.0.2.0`** for multi-port Grout configs. This increments
the third octet by 2 per port pair, aligning exactly with the `/24` subnet layout.

---

## 8. CPU Affinity Configuration

### 8.1 When to Set CPU Affinity

CPU affinity is **recommended** for multi-port configs and **required** when Grout
shares a host with TRex or other DPDK applications.

### 8.2 Guidelines

```
Host CPUs:  [0] [1] [2] [3] [4] [5] [6] [7] [8] [9] ...
             │         │    │    └──────────────────── Grout datapath
             │         │    └─────────────────────── Grout control
             │         └──────────────────────────── OS / housekeeping
             └────────────────────────────────────── OS / housekeeping
```

- **Control CPUs** (1–2 cores): Handle grcli commands, ARP, management. Low utilization.
- **Datapath CPUs** (2+ cores): Handle packet forwarding in the graph pipeline. Scale with port count.
- Avoid sharing NUMA nodes between TRex and Grout when possible.
- Keep `grout-rxqs=1` for virtio-net (VMs). Increase only for bare-metal NICs.

### 8.3 Example

```json
{ "arg": "grout-datapath-cpus", "vals": ["6,7,8,9"], "role": "server" },
{ "arg": "grout-control-cpus", "vals": ["4,5"], "role": "server" }
```

Generates: `affinity cpus set control 4,5 datapath 6,7,8,9`

---

## 9. Data Collection and Observability

### 9.1 Periodic Stats (During Test)

The `grout-stats-collector.sh` runs in the background at 5-second intervals, producing:

| File | Content | Format |
|------|---------|--------|
| `trafficgen-grout-hw-stats.csv` | Per-port RX/TX packets, bytes, errors, drops | CSV with timestamp |
| `trafficgen-grout-sw-stats.csv` | Per-graph-node calls, packets, cycles/pkt | CSV with timestamp |

### 9.2 Post-Test Snapshot (At Stop)

`trafficgen-server-stop` captures a final comprehensive dump:

| File | Content |
|------|---------|
| `trafficgen-grout-post-test-stats.txt` | Software stats, hardware stats, interface state, nexthop table, route table, graph config, CPU affinity |

### 9.3 Key Metrics to Watch

| Metric (SW stats) | Healthy Value | Problem Indicator |
|-------------------|---------------|-------------------|
| `ip_forward` | Equal to `ip_input` | — |
| `ip_hold` | 0 or near 0 | High = nexthop/ARP issues |
| `arp_input_request_drop` | 0 | High = ARP not working |
| `port_tx-pN` | Proportional to `port_rx` | Low = forwarding blocked |

---

## 10. Grout Version Management

### 10.1 Bundled RPM (Default)

Grout v0.16.0 is bundled as `trafficgen/grout/grout.x86_64.rpm` and installed at
image build time. No internet access required.

### 10.2 Runtime Version Override

To use a different version, add to the runfile:

```json
{ "arg": "grout-version", "vals": ["v0.17.0"], "role": "server" }
```

At runtime, `install-grout.sh` compares the requested version with the installed
version. If they differ, it downloads from GitHub. This requires internet access.

### 10.3 Updating the Bundled RPM

```bash
cd /opt/crucible/repos/.../bench-trafficgen/trafficgen/grout/
curl -LO https://github.com/DPDK/grout/releases/download/v0.17.0/grout.x86_64.rpm
# Update the default version in install-grout.sh
# Rebuild engine images: crucible update
```

---

## 11. Troubleshooting

### 11.1 "No infra message found"

**Cause:** Auto-discovery messaging failed. TRex MACs were not delivered to the server.

**Check:**
- Engine IDs match between client and server
- `engine-script-library` does not have `local cs_buddy=""` at line 654
- The pairing.json shows correct buddy mapping

### 11.2 "Failed to apply grout configuration"

**Cause:** A `grcli` command in the init file failed.

**Common reasons:**
- `rxqs` too high for virtio-net (keep at 1)
- IPv6 disabled in kernel (`ipv6.disable=1` in `/proc/cmdline`)
- PCI device not bound to `vfio-pci`

### 11.3 Low CPS / High `ip_hold` in ASTF

**Cause:** Nexthop entries only cover a single IP, not the full ASTF range.

**Fix:** The gateway route fix (`route add <subnet>/24 via <peer_ip>`) must be in
`trafficgen-server-start`. Verify the post-test stats show `ip_hold` near 0.

### 11.4 `rx_pps=0` During Ramp-Up

**Cause:** Grout cannot forward traffic back to TRex.

**Check:**
- Post-test `nexthop show` should list static entries for each port
- Post-test `route show` should list gateway routes for each subnet
- `arp_input_request_drop` should be 0

### 11.5 Multiplex Validation Errors

**Cause:** Device PCI addresses must use `VAR:` prefix format in multiplex validation.

**Fix:** Ensure PCI addresses are passed as standard format (e.g. `0000:af:00.0`)
and that `multiplex.json` has the correct validation regex.

---

## 12. Known Issues and Limitations

| Issue | Description | Workaround |
|-------|-------------|------------|
| Grout dynamic ARP on i40e/ice | Grout drops incoming ARP requests on Intel PF ports (upstream Issue #545) | Auto-discovery adds static nexthops — no manual config needed |
| virtio-net RX queue limit | `rxqs > 1` fails with `EOVERFLOW` on virtio-net | Keep `grout-rxqs=1` for VM ports |
| `grout-forward-mode` unused | Parsed but not applied in grcli commands | No action needed — IPv4 is the default |
| CPS limited by virtio-net | TCP throughput capped by OVS-DPDK + virtio double-crossing | Use SR-IOV VFs for higher performance |
| Alma9 required for TRex client | TRex Scapy needs Python < 3.12 (Alma10 has 3.12) | Always use `userenv=alma9` for client |
| Alma10 required for Grout server | Grout v0.16.0 needs glibc 2.38+ | Always use `userenv=alma10` for server |
