# Bench-trafficgen

## Purpose
Scripts and configuration to run traffic generation benchmarks within the crucible framework. Uses TRex and testpmd with binary search optimization for finding maximum throughput at a given loss rate.

## Languages
- Bash: wrapper scripts (trafficgen-base, trafficgen-client, trafficgen-server-start/stop, trafficgen-infra, trafficgen-import-files)
- Python: core implementation in `trafficgen/` subdirectory (binary-search.py, tg_lib.py, trex-txrx.py, profile-builder.py, etc.) and `trafficgen-post-process.py`

## Key Files
| File | Purpose |
|------|---------|
| `rickshaw.json` | Rickshaw integration: client/server/infra scripts, parameter transformations |
| `multiplex.json` | Parameter validation, presets, and device/protocol options |
| `trafficgen-client` | Runs binary-search.py with DPDK device resolution |
| `trafficgen-server-start/stop` | Manages testpmd server |
| `trafficgen-infra` | Launches and validates TRex service |
| `trafficgen-post-process` | Parses test JSON into CDM-compliant metrics |
| `trafficgen/binary-search.py` | Core binary search algorithm for throughput testing |
| `trafficgen/tg_lib.py` | Traffic generator library |
| `client-workshop.json` | Client engine image build: TRex, DPDK, and dependencies (alma9 userenv) |
| `server-workshop.json` | Server engine image build: testpmd and dependencies |

## Conventions
- Primary branch is `main`
- Modular design: wrapper scripts at root, core implementation in `trafficgen/`
- TRex v3.08 (DPDK 25.07) on alma9 userenv
- Traffic profiles defined as JSON in `trafficgen/` subdirectory
- Mellanox NICs require `trex-software-mode=on` and `trex-mellanox-support=on` for performance (enables multi-queue RX via RSS instead of single-queue hardware filter mode)
