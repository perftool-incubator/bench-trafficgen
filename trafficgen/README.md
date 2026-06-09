# trafficgen
This is a collection of traffic generator scripts for use with TRex (https://trex-tgn.cisco.com/).  Please see the respective README files depending on your needs.

script | description | README
-------|-------------|-------
binary-search.py | This script is the primary interface through which trafficgen is operated.  It implements the binary search logic for finding maximum throughput and executes the specified traffic generator for running trials.  The binary search logic can be tested by using the null-txrx.py traffic generator.  | README-binary-search.md
trex-txrx.py | A simple TRex based stateless (STL) traffic generator that executes a single trial based on the provided arguments.  Usually invoked by binary-search.py. | (see binary-search --help)
trex-txrx-profile.py | A TRex stateless (STL) traffic generator that executes a single trial based on a supplied JSON profile file.  Usually invoked by binary-search.py. | README-trex-txrx-profile.md
trex-astf.py | TRex Advanced Stateful (ASTF) traffic generator that executes a single trial simulating real TCP/UDP client-server sessions.  Used for OVS+conntrack, NAT, and stateful firewall benchmarking.  Usually invoked by binary-search.py when --traffic-generator=trex-astf. | README-trex-astf.md
trex-query.py | Queries a TRex server (STL mode) for information about the requested ports.  Usually invoked by binary-search.py when using STL generators. |
trex-astf-query.py | Queries a TRex server (ASTF mode) for port information.  Used automatically when --traffic-generator=trex-astf since STLClient cannot connect to an ASTF-mode server. |
null-txrx.py | A faux traffic producer which is used to test the binary search logic of binary-search.py.  Usually invoked by binary-search.py. |
install-trex.sh | Installs TRex.  The version of TRex installed is hard coded because it has been tested for functionality and compatibility with trafficgen. |
launch-trex.sh | Developer tool to configure and launch the TRex server locally.  Supports --mode=stl (default) and --mode=astf for ASTF mode.  Not used in the Crucible/Rickshaw execution path. |
postprocess-trex-profiler.py | Process data collected by the trex-txrx-profile.py TRex profiler which captures TRex statistics while a trial is running.  This is run by binary-search.py and should usually not be directly invoked by an end user. |
profile-builder.py | Take simple, trex-txrx.py like arguments and generate a traffic profile usable by trex-txrx-profile.py |
reporter.py | Used to extract information about a binary-search.py run from the resulting binary-search.json file.  Supports both STL (packet loss %) and ASTF (CPS, connection error %) result formats. |
tg_lib.py | Library of generic Python routines that are shared across many of the scripts in this project.  Should not/cannot be directly invoked. |
trex_tg_lib.py | Library of TRex STL related Python routines that are shared between the STL traffic generators.  Should not/cannot be directly invoked. |
trex_astf_lib.py | Library of TRex ASTF related Python routines shared between the ASTF traffic generator scripts.  Should not/cannot be directly invoked. |
