# trex-astf.py -- TRex Advanced Stateful Traffic Generator

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

## Prerequisites

### System Requirements

1. **TRex >= v3.06** -- required for SACK, cubic/newreno TCP congestion control, XXV710 i40e fixes:
   ```bash
   # Specify version via multiplex parameter
   --trex-version=v3.06
   ```

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

Configure the DUT before running tests:

```bash
# Increase conntrack table size (default 65536 is too small for ASTF)
ovs-appctl dpctl/ct-set-maxconns 5000000

# Create zone timeout policy aligned to ASTF profile duration
# (adjust tcp_established to match your --astf-server-wait-ms * num-messages)
ovs-vsctl add-zone-tp netdev zone=0 \
    udp_first=1 udp_single=1 udp_multiple=30 \
    tcp_syn_sent=1 tcp_syn_recv=1 tcp_fin_wait=1 \
    tcp_time_wait=1 tcp_close=1 tcp_established=30

# OVS flow rules for conntrack tracking
cat > /tmp/ct-flows.txt << 'EOF'
priority=1 ip ct_state=-trk                   actions=ct(table=0)
priority=1 ip ct_state=+trk+new in_port=port0 actions=ct(commit),normal
priority=1 ip ct_state=+trk+est               actions=normal
priority=0                                     actions=drop
EOF
ovs-ofctl add-flows br0 /tmp/ct-flows.txt
```

## Quick Start

### Bare-Metal 8x25G XXV710 + OVS+conntrack

```bash
crucible run --tool trafficgen \
  --traffic-generator=trex-astf \
  --trex-version=v3.06 \
  --trex-devices=0000:18:00.0,0000:18:00.1,0000:18:02.0,0000:18:02.1,... \
  --astf-protocol=tcp \
  --astf-num-messages=1 \
  --astf-message-size=20 \
  --astf-max-flows=50000 \
  --astf-ramp-time=10 \
  --astf-max-error-pct=0.1 \
  --pre-trial-cmd="conntrack -F" \
  --search-runtime=30 \
  --validation-runtime=60
```

Device pairs are automatically mapped: `--trex-devices=0,1,2,3,4,5,6,7` → `--device-pairs=0:1,2:3,4:5,6:7`

### OpenShift SR-IOV Pod Deployment

PCI addresses are injected as environment variables by the SR-IOV Network Operator:

```bash
crucible run --tool trafficgen \
  --traffic-generator=trex-astf \
  --trex-version=v3.06 \
  --trex-devices=VAR:PCIDEVICE_OPENSHIFT_IO_DPDK_NIC_1,VAR:PCIDEVICE_OPENSHIFT_IO_DPDK_NIC_2 \
  --no-promisc=ON \
  --trex-software-mode=on \
  --astf-protocol=tcp \
  --astf-max-flows=50000 \
  --astf-ramp-time=10 \
  --astf-max-error-pct=0.1
```

### Using a Preset (NFV Scenario)

```bash
# Short-lived TCP: maximum connection creation/destruction rate
crucible run --tool trafficgen \
  --preset=astf_short_lived_tcp \
  --trex-devices=...
```

Available presets: `astf_short_lived_tcp`, `astf_long_lived_tcp`, `astf_mixed_nfv`

## Parameters Reference

### Core Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--traffic-generator` | `trex-txrx` | Set to `trex-astf` to enable ASTF mode |
| `--trex-version` | (image default) | TRex version: `v3.06`, `v2.87`, etc. |
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
--pre-trial-cmd="conntrack -F"
```

Expected: 30K-100K+ CPS depending on hardware and OVS PMD thread count.

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

### Conntrack Table Sizing Formula

```
connection_duration_sec = (num_messages × server_wait_ms × 2) / 1000
peak_flows = CPS × connection_duration_sec
max_flows_setting = peak_flows × 1.5  # safety margin
nf_conntrack_max = max_flows_setting × 2  # additional safety
```

### Timeout Policy Recommendations

| ASTF Profile | tcp_established | udp_multiple |
|-------------|-----------------|--------------|
| short-lived-tcp | 5s | n/a |
| long-lived-tcp | 60s | n/a |
| short-lived-udp | n/a | 5s |
| mixed-tcp-udp | 5s | 5s |
| http-like-tcp | 15s | n/a |

### Pre-Trial conntrack Flush

Use `--pre-trial-cmd` to flush conntrack between trials:

```bash
# Single command
--pre-trial-cmd="conntrack -F"

# Multiple commands (wrap in shell)
--pre-trial-cmd="sh -c 'conntrack -F; ovs-appctl dpctl/flush-conntrack'"
```

## ASTF Binary Search Flow

```
binary-search.py starts
  └─ rate = initial_rate (default 100.0 × ASTF_MULTIPLIER = 10000 CPS)
  │
  ├─ get_trex_port_info() → trex-astf-query.py → ASTFClient.get_port_attr()
  │
  └─ Search Loop:
       ├─ [optional] run --pre-trial-cmd
       ├─ Spawn: trex-astf.py --mult=rate
       │    ├─ ASTFClient.connect()
       │    ├─ reset() → load_profile() → start(mult=rate)
       │    ├─ wait_for_cps_stable()  (ramp-up phase)
       │    ├─ clear_stats() → sleep(runtime) → get_stats()
       │    ├─ stop() → disconnect()
       │    └─ emit "PARSABLE RESULT: {astf_json}" on stderr
       │
       ├─ evaluate_trial_astf():
       │    Phase 1: connections_attempted == 0? → abort
       │    Phase 2: ASTF err counters non-zero? → fail
       │    Phase 3: connection_error_pct > --astf-max-error-pct? → fail
       │    Phase 4: retransmit_pct > --astf-max-retransmit-pct? → fail (opt.)
       │    Phase 5: UDP drop_pct > threshold (mixed mode)? → fail
       │    Phase 6: actual CPS outside rate_tolerance? → retry
       │    Phase 7: timeout/force_quit? → retry/quit
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
| **L7 TX/RX BW** | `m_tx_bw_l7_r`, `m_rx_bw_l7_r` | Application-layer bandwidth |

## Troubleshooting

### Connection Error Rate Too High

- Reduce `--rate` starting point or `--min-rate`
- Reduce `--astf-max-flows` to stay within conntrack table limits
- Flush conntrack before trials: `--pre-trial-cmd="conntrack -F"`
- Check DUT conntrack table: `ovs-appctl dpctl/dump-conntrack | wc -l`

### TRex Fails to Start in ASTF Mode

- Verify `--traffic-generator=trex-astf` is set (trafficgen-infra adds `--astf` automatically)
- Check `trex-server-stderrout.txt` in the sample directory
- Verify TRex v3.06+ is installed: `ls /opt/trex/`
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
