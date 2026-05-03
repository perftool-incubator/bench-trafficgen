# Bench-trafficgen

## Purpose
Scripts and configuration to run traffic generation benchmarks within the crucible framework.
Uses TRex and testpmd with binary search optimization for:
- Finding maximum packet forwarding throughput at a given loss rate (STL/stateless mode)
- Finding maximum connection rate (CPS) for stateful DUT validation (ASTF mode)

## Languages
- Bash: wrapper scripts (trafficgen-base, trafficgen-client, trafficgen-server-start/stop, trafficgen-infra, trafficgen-import-files)
- Python: core implementation in `trafficgen/` subdirectory (binary-search.py, tg_lib.py, trex-txrx.py, trex-astf.py, etc.)
- Perl: trafficgen-post-process

## Key Files
| File | Purpose |
|------|---------|
| `rickshaw.json` | Rickshaw integration: client/server/infra scripts, parameter transformations |
| `multiplex.json` | Parameter validation, presets (including ASTF NFV presets), and device/protocol options |
| `trafficgen-client` | Runs binary-search.py with DPDK device resolution; strips infra params from passthru |
| `trafficgen-server-start/stop` | Manages testpmd server |
| `trafficgen-infra` | Launches TRex service; handles `--trex-version` runtime version selection; adds `--astf` flag when `traffic-generator=trex-astf` |
| `trafficgen-post-process` | Parses test JSON into CDM-compliant metrics |
| `trafficgen/binary-search.py` | Core binary search algorithm; supports STL and ASTF backends |
| `trafficgen/tg_lib.py` | Generic traffic generator utilities |
| `trafficgen/trex_tg_lib.py` | TRex STL (stateless) packet builders and helpers |
| `trafficgen/trex_astf_lib.py` | TRex ASTF shared helpers: profile builders, stats extraction, ramp-up stabilization |
| `trafficgen/trex-astf.py` | ASTF trial runner: ASTFClient subprocess with TCP/UDP/mixed support, VLAN, IPv6 |
| `trafficgen/trex-astf-query.py` | Port info query for ASTF-mode TRex (STLClient cannot connect to ASTF server) |
| `trafficgen/astf-profiles/` | NFV scenario profiles: short-lived-tcp, long-lived-tcp, short-lived-udp, mixed-tcp-udp, http-like-tcp, vlan-tcp |
| `trafficgen/README-trex-astf.md` | Complete ASTF user guide |
| `workshop.json` | Container image build: TRex v2.87 (default), DPDK, Python dependencies |

## Conventions
- Primary branch is `main`; ASTF feature development on `astf-feature-test` (pradiptapks fork)
- Modular design: wrapper scripts at root, core implementation in `trafficgen/`
- Supports TRex STL, TRex ASTF, and MoonGen traffic generators
- STL traffic profiles: JSON files in `trafficgen/trex-profiles/` (validated against `traffic-profile-schema.json`)
- ASTF traffic profiles: Python `.py` files in `trafficgen/astf-profiles/` (NOT validated by JSON schema)

## Development Context
- Active feature branch: `astf-feature-test` on remote `pradiptapks`
  (https://github.com/pradiptapks/bench-trafficgen)
- Upstream: `origin` (https://github.com/perftool-incubator/bench-trafficgen)
- TRex version selection: `--trex-version=vX.YY` flows from multiplex.json → trafficgen-infra → runtime install/symlink update
- Default TRex version is `v2.87` (from `install-trex.sh` default); override with `--trex-version` in multiplex at runtime
