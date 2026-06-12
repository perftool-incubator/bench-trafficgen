# Bench-trafficgen

## Purpose
Scripts and configuration to run traffic generation benchmarks within the crucible framework.
Uses TRex and testpmd with binary search optimization for:
- Finding maximum packet forwarding throughput at a given loss rate (STL/stateless mode)
- Finding maximum connection rate (CPS) for stateful DUT validation (ASTF mode)

## Languages
- Bash: wrapper scripts (trafficgen-base, trafficgen-client, trafficgen-server-start/stop, trafficgen-infra, trafficgen-import-files)
- Python: core implementation in `trafficgen/` subdirectory (binary-search.py, tg_lib.py, trex-txrx.py, trex-astf.py, etc.) and `trafficgen-post-process.py`

## Key Files
| File | Purpose |
|------|---------|
| `rickshaw.json` | Rickshaw integration: client/server/infra scripts, parameter transformations |
| `multiplex.json` | Parameter validation, presets (including ASTF NFV presets), and device/protocol options |
| `trafficgen-client` | Runs binary-search.py with DPDK device resolution; strips infra params from passthru |
| `trafficgen-server-start/stop` | Manages server DUT: testpmd (L2), grout (L3), or null (passthrough) |
| `trafficgen-infra` | Launches TRex service; adds `--astf` flag when `traffic-generator=trex-astf` |
| `trafficgen-post-process.py` | Parses test JSON into CDM-compliant metrics (STL and ASTF) |
| `trafficgen/binary-search.py` | Core binary search algorithm; supports STL and ASTF backends |
| `trafficgen/tg_lib.py` | Generic traffic generator utilities |
| `trafficgen/trex_tg_lib.py` | TRex STL (stateless) packet builders and helpers |
| `trafficgen/trex_astf_lib.py` | TRex ASTF shared helpers: profile builders, stats extraction, ramp-up stabilization |
| `trafficgen/trex-astf.py` | ASTF trial runner: ASTFClient subprocess with TCP/UDP/mixed support, VLAN, IPv6 |
| `trafficgen/trex-astf-query.py` | Port info query for ASTF-mode TRex (STLClient cannot connect to ASTF server) |
| `trafficgen/astf-profiles/` | NFV scenario profiles: short-lived-tcp, long-lived-tcp, short-lived-udp, mixed-tcp-udp, http-like-tcp, vlan-tcp |
| `trafficgen/README-trex-astf.md` | Complete ASTF user guide |
| `trafficgen/install-grout.sh` | Grout installer: bundled RPM fallback + GitHub download for version override |
| `trafficgen/grout/grout.x86_64.rpm` | Bundled Grout RPM (v0.16.0) for offline installation |
| `trafficgen/grout-stats-collector.sh` | Periodic Grout stats poller: hardware (per-port) + software (per-node) CSV output |
| `client-workshop.json` | Client engine image build: TRex, DPDK, and dependencies (alma9 userenv) |
| `server-workshop.json` | Server engine image build: testpmd and dependencies, Grout (alma9/alma10 userenvs) |

## Conventions
- Primary branch is `main`
- Modular design: wrapper scripts at root, core implementation in `trafficgen/`
- TRex v3.08 (DPDK 25.07) on alma9 userenv
- Supports TRex STL, TRex ASTF, and testpmd traffic generators
- STL traffic profiles: JSON files in `trafficgen/trex-profiles/` (validated against `traffic-profile-schema.json`)
- ASTF traffic profiles: Python `.py` files in `trafficgen/astf-profiles/` (NOT validated by JSON schema)
- Default TRex version is configured in `trafficgen/install-trex.sh`
- Mellanox NICs require `trex-software-mode=on` and `trex-mellanox-support=on` for performance (enables multi-queue RX via RSS instead of single-queue hardware filter mode)
- Default Grout version is configured in `trafficgen/install-grout.sh` (v0.16.0); the bundled RPM at `trafficgen/grout/grout.x86_64.rpm` is installed offline at image build time; a different version can be requested at runtime via the `--grout-version` runfile parameter (triggers a GitHub download only when the requested version differs from bundled)
- Server `switch-type` controls the DUT: `testpmd` (L2 forwarding), `grout` (L3 IPv4/IPv6 forwarding via Grout DPDK router), or `null` (no DUT)
- Grout parameters use `--grout-*` prefix: `--grout-ip-addrs`, `--grout-routes`, `--grout-forward-mode`, `--grout-rxqs`, `--grout-qsize`, `--grout-datapath-cpus`, `--grout-control-cpus`, `--grout-static-arp`, `--grout-version`
- Grout integration is purely server-side; all three TRex backends (trex-txrx, trex-txrx-profile, trex-astf) work with Grout unmodified
- Grout CPU affinity (`affinity cpus set`) is ONLY applied when `--grout-datapath-cpus` is explicitly set; automatic fallback to WORKLOAD_CPUS is intentionally avoided to prevent graph restarts
- **Auto MAC/IP collection**: When `--grout-static-arp` is omitted from the runfile, `trafficgen-server-start` auto-generates nexthop entries from the TRex infra message (MACs + IPs sent by `trafficgen-infra`). Similarly, `trafficgen-client` auto-collects Grout's port MACs from the server message and overrides any manually-specified `--dst-macs`. This eliminates the need for manual MAC/IP configuration in most Grout runfiles. The `--src-ips` param (client-role) is embedded in the infra message so the server knows which IPs to pair with each TRex MAC for nexthop entries. If `--src-ips` is not set, IPs are derived from the Grout subnet (host part replaced with `.100`). Manual `--grout-static-arp` and `--dst-macs` in the runfile still work as overrides.

## Known Issues (Grout Integration)

| Issue | Impact | Workaround |
|-------|--------|------------|
| [DPDK/grout#545](https://github.com/DPDK/grout/issues/545): ARP doesn't work on hardware PF ports (i40e, ice) | Dynamic ARP resolution fails; nexthop stays unresolved | Auto-generated from infra message; use `--grout-static-arp` to override |
| `affinity cpus set` triggers full graph restart | All datapath workers destroyed/recreated; can disrupt nexthop state | Don't set explicit CPU affinity unless needed; let Grout auto-detect |
| Connected routes require ARP for next-hop MAC | Even with static nexthops, fast-path activation may be delayed | Nexthops are auto-generated; ensure `--src-ips` is set for accurate IP-to-MAC pairing |
| Too many datapath CPUs for few RX queues | Excessive workers (e.g., 26 for 2 queues) waste resources | Match `--grout-datapath-cpus` count to `rxqs * num_ports` |

## Grout Version Management

Grout follows the same offline-first pattern as TRex:

- **Bundled RPM**: `trafficgen/grout/grout.x86_64.rpm` is committed to the repo and copied into the engine image at build time via `server-workshop.json` (no internet needed)
- **Install script**: `trafficgen/install-grout.sh` handles installation — compares the requested version against the bundled RPM version and installs locally if they match, or downloads from GitHub if they differ
- **Runtime override**: Users can set `grout-version=vX.Y.Z` in the runfile (validated by `multiplex.json`); `trafficgen-server-start` calls `install-grout.sh --version vX.Y.Z --insecure` at runtime only when the requested version differs from what is installed
- **Updating the bundled version**: Download the new RPM to `trafficgen/grout/grout.x86_64.rpm`, update the default version in `install-grout.sh`, and commit

## Grout Data Collection

Grout data collection operates at two levels:

### Periodic stats (during test)
`trafficgen-server-start` launches `grout-stats-collector.sh` as a background process after Grout configuration is applied and FIB has settled. Stats counters are reset (`stats reset`) before the collector starts so counters only reflect test traffic.

Output files:
- `trafficgen-grout-hw-stats.csv` — per-port hardware counters (rx/tx packets, bytes, errors, drops) sampled every 5 seconds
- `trafficgen-grout-sw-stats.csv` — per-graph-node software counters (calls, packets, cycles/pkt) sampled every 5 seconds

The collector is stopped by `trafficgen-server-stop` before the Grout daemon is killed.

### Post-test snapshot (at stop)
`trafficgen-server-stop` captures a comprehensive state dump to `trafficgen-grout-post-test-stats.txt` before killing the daemon:
- `stats show software` — cumulative graph node cycle counts
- `stats show hardware` — cumulative per-port packet/byte counters
- `interface show` — final interface state and MACs
- `nexthop show` — final nexthop reachability (static vs. new vs. reachable)
- `route show` — active routes
- `graph config show` — vector/burst size configuration
- `affinity show` — CPU-to-queue pinning

## Grout L3 Testing Requirements

For functional validation with Grout as DUT:
1. Server `userenv=alma10` (Grout v0.16.0 requires glibc 2.38+)
2. Client `userenv=alma9` (TRex bundled Scapy requires Python <3.12)
3. Set `--grout-ip-addrs` (server-role) with IP/prefix per Grout port (e.g., `10.0.0.1/24,10.0.1.1/24`)
4. Set `--src-ips` (client-role) with TRex source IPs matching the Grout subnets — these are auto-forwarded to the server for nexthop generation
5. `--grout-static-arp` and `--dst-macs` are auto-collected via rickshaw messaging and no longer need to be manually specified
6. Optional: set `--grout-static-arp` (server-role) to override auto-generated nexthops; set `--dst-macs` (client-role) to override auto-collected Grout MACs
7. Optional: set `--grout-version` (server-role) to request a specific Grout version at runtime (e.g., `v0.17.0`)
