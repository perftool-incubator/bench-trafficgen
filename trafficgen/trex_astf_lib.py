# -*- mode: python; indent-tabs-mode: nil; python-indent-offset: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

"""
Shared library for TRex Advanced Stateful (ASTF) traffic generation.

Provides:
  - astf_null_stats()         -- zero-value stats template for ASTF trials
  - extract_astf_stats()      -- normalize raw ASTF get_stats() output
  - wait_for_cps_stable()     -- ramp-up stabilization (mirrors cps_ndr.py)
  - build_tcp_profile()       -- parameterized TCP ASTFProfile
  - build_udp_profile()       -- parameterized UDP ASTFProfile
  - build_mixed_profile()     -- mixed TCP+UDP ASTFProfile (mirrors cps_ndr.py)
  - load_astf_profile_file()  -- load external .py ASTF profile
  - validate_ip_ranges()      -- sanity-check IP range parameters

ASTF multiplier base: profile templates use cps=ASTF_MULTIPLIER as base CPS.
ASTFClient.start(mult=M) scales to actual CPS = M * ASTF_MULTIPLIER.
"""

from __future__ import print_function

import sys
import time
import importlib.util

sys.path.append('/opt/trex/current/automation/trex_control_plane/interactive')

ASTF_MULTIPLIER = 100  # base CPS in profile templates (same as cps_ndr.py)


def astf_null_stats():
    """
    Return a zeroed-out stats dict for ASTF trials.
    Parallel to the null_stats dict used in binary-search.py for STL generators.
    """
    return {
        'cps':                      0.0,
        'active_flows':             0,
        'established_flows':        0,
        'tx_l7_bps':                0.0,
        'rx_l7_bps':                0.0,
        'tx_pps':                   0.0,
        'rx_pps':                   0.0,
        'tx_bps':                   0.0,
        'rx_bps':                   0.0,
        'tx_packets':               0,
        'rx_packets':               0,
        'connections_attempted':    0,
        'connections_established':  0,
        'connections_closed':       0,
        'connections_dropped':      0,
        'connection_error_pct':     0.0,
        'retransmit_pct':           0.0,
        'out_of_order_pct':         0.0,
        'tcp_retransmit_packets':   0,
        'udp_tx_packets':           0,
        'udp_rx_packets':           0,
        'udp_drop_pct':             0.0,
        # ICMP latency (from start(latency_pps=N))
        'latency_avg_usec':         0.0,
        'latency_max_usec':         0.0,
        'latency_min_usec':         0.0,
        'latency_jitter_usec':      0.0,
        # TCP latency (available in TRex >= v3.06)
        'tcp_syn_ack_latency_usec': 0.0,
        'tcp_req_resp_latency_usec':0.0,
        # Server-side counters
        'server_accepts':           0,
        'server_connects':          0,
        'server_drops':             0,
        # TCP overhead counters
        'tcp_snd_total':            0,
        'tcp_snd_ctrl':             0,
        'tcp_snd_acks':             0,
        'tcp_snd_bytes':            0,
        'tcp_rcv_bytes':            0,
        'tcp_overhead_pct':         0.0,
        # TCP stack RTT/RTO (from get_flow_info() per-connection sampling)
        'tcp_rtt_avg_usec':         0.0,
        'tcp_rtt_min_usec':         0.0,
        'tcp_rtt_max_usec':         0.0,
        'tcp_rto_avg_usec':         0.0,
        # Error-scenario counters (non-zero indicates DUT problems)
        'tcp_keepalive_drops':      0,
        'tcp_persist_drops':        0,
        'tcp_retransmit_timeouts':  0,
        'tcp_syn_retransmit_timeouts': 0,
        'tcp_conn_drops':           0,
        # Per-port stats (list of dicts, one per port)
        'port_stats':               [],
        # Per-template-group stats (dict keyed by template name)
        'template_stats':           {},
        'has_astf_errors':          False,
        'astf_error_detail':        {}
    }


def extract_astf_stats(raw_result):
    """
    Normalize raw ASTF PARSABLE RESULT JSON into astf_null_stats() shape.

    raw_result is the full parsed JSON dict from trex-astf.py, which includes
    keys: 'astf', 'global', 'total', 'trial_start', 'trial_stop'.
    """
    stats = astf_null_stats()

    raw_astf = raw_result.get('astf', {})
    raw_global = raw_result.get('global', {})
    raw_total = raw_result.get('total', {})

    client = raw_astf.get('client', {})
    err = raw_astf.get('err', {})

    # TCP connection-level counters (tcps_* prefix in client dict)
    tcp_attempted  = int(client.get('tcps_connattempt', 0))
    tcp_established = int(client.get('tcps_connects', 0))
    tcp_closed      = int(client.get('tcps_closed', 0))
    tcp_dropped     = int(client.get('tcps_drops', 0))
    snd_pack    = int(client.get('tcps_sndpack', 0))
    retx_pack   = int(client.get('tcps_sndrexmitpack', 0))
    rcv_pack    = int(client.get('tcps_rcvpack', 0))
    oo_pack     = int(client.get('tcps_rcvoopack', 0))

    # UDP connection-level counters (udps_* prefix in same client dict)
    udp_connects = int(client.get('udps_connects', 0))
    udp_closed   = int(client.get('udps_closed', 0))
    udp_sndpkt   = int(client.get('udps_sndpkt', 0))
    udp_rcvpkt   = int(client.get('udps_rcvpkt', 0))

    stats['udp_tx_packets'] = udp_sndpkt
    stats['udp_rx_packets'] = udp_rcvpkt

    # Combined TCP + UDP connection counts
    stats['connections_attempted']   = tcp_attempted + udp_connects
    stats['connections_established'] = tcp_established + udp_connects
    stats['connections_closed']      = tcp_closed + udp_closed
    stats['connections_dropped']     = tcp_dropped

    stats['tcp_retransmit_packets'] = retx_pack

    total_attempted = stats['connections_attempted']
    if total_attempted > 0:
        stats['connection_error_pct'] = 100.0 * tcp_dropped / total_attempted
    if snd_pack > 0:
        stats['retransmit_pct'] = 100.0 * retx_pack / snd_pack
    if rcv_pack > 0:
        stats['out_of_order_pct'] = 100.0 * oo_pack / rcv_pack

    # Item 5: TCP overhead counters (control vs data ratio)
    tcp_snd_total = int(client.get('tcps_sndtotal', 0))
    tcp_snd_ctrl  = int(client.get('tcps_sndctrl', 0))
    tcp_snd_acks  = int(client.get('tcps_sndacks', 0))
    tcp_snd_bytes = int(client.get('tcps_sndbyte', 0))
    tcp_rcv_bytes = int(client.get('tcps_rcvbyte', 0))
    stats['tcp_snd_total']    = tcp_snd_total
    stats['tcp_snd_ctrl']     = tcp_snd_ctrl
    stats['tcp_snd_acks']     = tcp_snd_acks
    stats['tcp_snd_bytes']    = tcp_snd_bytes
    stats['tcp_rcv_bytes']    = tcp_rcv_bytes
    if tcp_snd_total > 0:
        stats['tcp_overhead_pct'] = 100.0 * (tcp_snd_ctrl + tcp_snd_acks) / tcp_snd_total

    # Item 8: Error-scenario counters (non-zero indicates DUT problems)
    stats['tcp_keepalive_drops']        = int(client.get('tcps_keepdrops', 0))
    stats['tcp_persist_drops']          = int(client.get('tcps_persistdrop', 0))
    stats['tcp_retransmit_timeouts']    = int(client.get('tcps_rexmttimeo', 0))
    stats['tcp_syn_retransmit_timeouts']= int(client.get('tcps_rexmttimeo_syn', 0))
    stats['tcp_conn_drops']             = int(client.get('tcps_conndrops', 0))

    # UDP drop percentage (based on sent vs received datagrams)
    if udp_sndpkt > 0 and udp_sndpkt > udp_rcvpkt:
        stats['udp_drop_pct'] = 100.0 * (udp_sndpkt - udp_rcvpkt) / udp_sndpkt

    # TCP latency (available in TRex >= v3.06 ASTF latency stats)
    # Earlier versions (v3.04) may not populate these fields
    raw_latency = raw_astf.get('latency', {})
    if raw_latency:
        stats['tcp_syn_ack_latency_usec']  = float(raw_latency.get('syn_ack_avg', 0.0))
        stats['tcp_req_resp_latency_usec'] = float(raw_latency.get('req_resp_avg', 0.0))

    # Bandwidth/rate counters
    stats['tx_l7_bps']          = float(client.get('m_tx_bw_l7_r', 0.0))
    stats['rx_l7_bps']          = float(client.get('m_rx_bw_l7_r', 0.0))
    stats['tx_pps']             = float(client.get('m_tx_pps_r', 0.0))
    stats['rx_pps']             = float(client.get('m_rx_pps_r', 0.0))
    stats['active_flows']       = int(client.get('m_active_flows', 0))
    stats['established_flows']  = int(client.get('m_est_flows', 0))

    # Global stats
    stats['cps']    = float(raw_global.get('tx_cps', 0.0))
    stats['tx_bps'] = float(raw_global.get('tx_bps', 0.0))
    stats['rx_bps'] = float(raw_global.get('rx_bps', 0.0))

    # Total packet counts
    stats['tx_packets'] = int(raw_total.get('opackets', 0))
    stats['rx_packets'] = int(raw_total.get('ipackets', 0))

    # Server-side counters (from server dict in same traffic stats)
    server = raw_astf.get('server', {})
    stats['server_accepts']  = int(server.get('tcps_accepts', 0)) + int(server.get('udps_accepts', server.get('udps_connects', 0)))
    stats['server_connects'] = int(server.get('tcps_connects', 0)) + int(server.get('udps_connects', 0))
    stats['server_drops']    = int(server.get('tcps_drops', 0))

    # TCP RTT/RTO from get_flow_info() -- aggregate RTT across sampled active flows.
    # These come from the ASTF TCP stack's internal RTT measurements -- more
    # accurate than ICMP for TCP workloads as they reflect actual TCP
    # data-path latency including DUT conntrack processing overhead.
    raw_tcp_info = raw_result.get('tcp_info', {})
    if raw_tcp_info:
        stats['tcp_rtt_avg_usec'] = float(raw_tcp_info.get('tcp_rtt_avg_usec', 0.0))
        stats['tcp_rtt_min_usec'] = float(raw_tcp_info.get('tcp_rtt_min_usec', 0.0))
        stats['tcp_rtt_max_usec'] = float(raw_tcp_info.get('tcp_rtt_max_usec', 0.0))
        stats['tcp_rto_avg_usec'] = float(raw_tcp_info.get('tcp_rto_avg_usec', 0.0))

    # ICMP latency stats (from start(latency_pps=N))
    raw_lat = raw_result.get('latency', {})
    if raw_lat:
        stats['latency_avg_usec']    = float(raw_lat.get('average', 0.0))
        stats['latency_max_usec']    = float(raw_lat.get('total_max', 0.0))
        stats['latency_min_usec']    = float(raw_lat.get('total_min', 0.0))
        stats['latency_jitter_usec'] = float(raw_lat.get('jitter', 0.0))

    # Per-port stats (list of per-port dicts)
    raw_ports = raw_result.get('port_stats', [])
    stats['port_stats'] = raw_ports

    # Per-template-group stats
    raw_tg = raw_result.get('template_stats', {})
    stats['template_stats'] = raw_tg

    # ASTF error counters
    if err:
        stats['has_astf_errors'] = True
        stats['astf_error_detail'] = dict(err)

    return stats


TCP_RTT_SHIFT = 5
TCP_RTTVAR_SHIFT = 4
MAX_RTT_SAMPLE_FLOWS = 10000


def aggregate_flow_rtt(flow_info, log_fn=None):
    """
    Aggregate TCP RTT data from get_flow_info() output.

    TRex stores smoothed RTT as (msec << TCP_RTT_SHIFT), i.e. raw value is
    msec * 32.  We convert to microseconds: usec = raw * 1000 / 32.

    Returns dict with tcp_rtt_avg_usec, tcp_rtt_min_usec, tcp_rtt_max_usec,
    tcp_rtt_samples, tcp_rto_avg_usec.  All zero if no valid samples.
    """
    if log_fn is None:
        log_fn = print

    result = {
        'tcp_rtt_avg_usec': 0.0,
        'tcp_rtt_min_usec': 0.0,
        'tcp_rtt_max_usec': 0.0,
        'tcp_rtt_samples':  0,
        'tcp_rto_avg_usec': 0.0,
    }

    if not flow_info or not isinstance(flow_info, dict):
        log_fn("TCP RTT: get_flow_info() returned empty (dump_interval may be 0)")
        return result

    rtt_values = []
    rto_sum = 0.0
    sampled = 0

    for flow_id, flow_data_list in flow_info.items():
        if flow_id in ('next_index',):
            continue
        if not isinstance(flow_data_list, list):
            continue
        for fd in flow_data_list:
            if not isinstance(fd, dict):
                continue
            raw_rtt = fd.get('rtt', 0)
            if raw_rtt and raw_rtt > 0:
                rtt_usec = float(raw_rtt) * 1000.0 / (1 << TCP_RTT_SHIFT)
                rtt_values.append(rtt_usec)
                rto_raw = fd.get('rto', 0)
                if rto_raw and rto_raw > 0:
                    rto_sum += float(rto_raw) * 1000.0
                sampled += 1
                if sampled >= MAX_RTT_SAMPLE_FLOWS:
                    break
        if sampled >= MAX_RTT_SAMPLE_FLOWS:
            break

    if rtt_values:
        rtt_values.sort()
        n = len(rtt_values)
        result['tcp_rtt_avg_usec'] = sum(rtt_values) / n
        result['tcp_rtt_min_usec'] = rtt_values[0]
        result['tcp_rtt_max_usec'] = rtt_values[-1]
        result['tcp_rtt_samples']  = n
        result['tcp_rto_avg_usec'] = rto_sum / n if n > 0 else 0.0
        log_fn("TCP RTT sampled %d flows: avg=%.1f min=%.1f max=%.1f usec" % (
            n, result['tcp_rtt_avg_usec'], result['tcp_rtt_min_usec'],
            result['tcp_rtt_max_usec']))
    else:
        log_fn("TCP RTT: no valid RTT samples from get_flow_info()")

    return result


def wait_for_cps_stable(client, ramp_time_sec, tolerance=0.01, log_fn=None):
    """
    Wait until the TRex ASTF connection rate (tx_cps) is stable.

    Polls get_stats() every second until the delta between consecutive
    tx_pps samples is < tolerance (1% by default), up to a maximum of
    3 * ramp_time_sec seconds.

    Includes early abort: if after ramp_time_sec seconds both tx_pps and
    rx_pps are still zero, exits immediately with a warning (likely L2/MAC
    misconfiguration -- no point waiting longer).

    This mirrors the ramp-up stabilization logic in cps_ndr.py.
    """
    if log_fn is None:
        log_fn = print

    log_fn("Waiting for CPS to stabilize (ramp_time=%ds, tolerance=%.1f%%)" % (
        ramp_time_sec, tolerance * 100))

    pps = None
    max_iters = 3 * ramp_time_sec
    for i in range(max_iters):
        time.sleep(1)
        stats = client.get_stats()
        g = stats.get('global', {})
        cur_pps = g.get('tx_pps', 0) or 0
        cur_rx  = g.get('rx_pps', 0) or 0
        cur_cps = g.get('tx_cps', 0) or 0

        # Early abort: if we've waited at least ramp_time_sec and there is
        # zero RX traffic, something is fundamentally wrong (L2 MAC, DUT not
        # forwarding, wrong ports). Exit ramp-up to let the trial proceed
        # and fail with a meaningful error instead of hanging forever.
        if i >= ramp_time_sec and cur_rx <= 0 and cur_pps <= 0:
            log_fn("ERROR: No TX/RX traffic after %ds. Possible causes:" % (i + 1))
            log_fn("  - DUT (testpmd) not forwarding (check testpmd log)")
            log_fn("  - Missing --dst-macs (L2 MAC not configured)")
            log_fn("  - TRex not started with --astf flag")
            log_fn("  - Physical cable/port connectivity issue")
            log_fn("Aborting ramp-up to allow trial to fail cleanly.")
            return

        if i >= ramp_time_sec and cur_pps > 0 and cur_rx <= 0:
            log_fn("WARNING: TX active (%.0f pps) but RX=0 after %ds. "
                    "DUT may not be forwarding return traffic." % (cur_pps, i + 1))

        if pps is not None and pps > 0 and abs(cur_pps - pps) / max(pps, 1) < tolerance:
            log_fn("CPS stable after %d seconds (tx_pps=%.0f, rx_pps=%.0f, tx_cps=%.0f)" % (
                i + 1, cur_pps, cur_rx, cur_cps))
            return
        pps = cur_pps

        if (i + 1) % 5 == 0:
            log_fn("  ramp-up %ds: tx_pps=%.0f rx_pps=%.0f tx_cps=%.0f" % (
                i + 1, cur_pps, cur_rx, cur_cps))

    log_fn("WARNING: CPS not fully stable after %d seconds (tx_pps=%.0f, rx_pps=%.0f)" % (
        max_iters, pps or 0, cur_rx))


def _build_ip_gen(client_start, client_end, server_start, server_end, ip_offset):
    """
    Build an ASTFIPGen with the given client/server IP ranges.
    """
    from trex.astf.api import ASTFIPGen, ASTFIPGenDist, ASTFIPGenGlobal
    return ASTFIPGen(
        glob=ASTFIPGenGlobal(ip_offset=ip_offset),
        dist_client=ASTFIPGenDist(
            ip_range=[client_start, client_end],
            distribution="seq"
        ),
        dist_server=ASTFIPGenDist(
            ip_range=[server_start, server_end],
            distribution="seq"
        )
    )


def build_tcp_profile(cps_base=ASTF_MULTIPLIER, message_size=64, num_messages=1,
                      server_wait_ms=0, max_flows=0, tcp_mss=1400,
                      client_ip_start="16.0.0.0", client_ip_end="16.0.255.255",
                      server_ip_start="48.0.0.0", server_ip_end="48.0.255.255",
                      ip_offset="1.0.0.0", tcp_port=8080,
                      rampup_sec=5, vlan_id=0, enable_ipv6=False,
                      ipv6_client_msb="ff02::", ipv6_server_msb="ff03::"):
    """
    Build a parameterized TCP ASTFProfile.

    Uses ASTFProgram(stream=True) with send/recv for TCP byte-stream semantics.
    """
    from trex.astf.api import (ASTFProfile, ASTFTemplate, ASTFProgram,
                                ASTFTCPClientTemplate, ASTFTCPServerTemplate,
                                ASTFGlobalInfo, ASTFAssociationRule)

    http_req  = b'x' * message_size
    http_resp = b'y' * message_size

    prog_c = ASTFProgram(stream=True)
    prog_s = ASTFProgram(stream=True)
    for _ in range(max(1, num_messages)):
        prog_c.send(http_req)
        prog_s.recv(message_size)
        if server_wait_ms > 0:
            prog_s.delay(server_wait_ms * 1000)
        prog_s.send(http_resp)
        prog_c.recv(message_size)

    ip_gen = _build_ip_gen(client_ip_start, client_ip_end,
                           server_ip_start, server_ip_end, ip_offset)

    c_glob = ASTFGlobalInfo()
    c_glob.scheduler.rampup_sec = rampup_sec
    c_glob.tcp.mss = tcp_mss
    if enable_ipv6:
        c_glob.ipv6.src_msb = ipv6_client_msb
        c_glob.ipv6.dst_msb = ipv6_server_msb
        c_glob.ipv6.enable  = 1

    limit = max_flows if max_flows > 0 else None

    template = ASTFTemplate(
        client_template=ASTFTCPClientTemplate(
            program=prog_c,
            ip_gen=ip_gen,
            port=tcp_port,
            cps=cps_base,
            limit=limit,
            cont=True
        ),
        server_template=ASTFTCPServerTemplate(
            program=prog_s,
            assoc=ASTFAssociationRule(port=tcp_port)
        ),
        tg_name='tcp-%d' % tcp_port
    )

    return ASTFProfile(
        default_ip_gen=ip_gen,
        default_c_glob_info=c_glob,
        templates=template
    )


def build_udp_profile(cps_base=ASTF_MULTIPLIER, message_size=64, num_messages=1,
                      server_wait_ms=0, max_flows=0,
                      client_ip_start="16.0.0.0", client_ip_end="16.0.255.255",
                      server_ip_start="48.0.0.0", server_ip_end="48.0.255.255",
                      ip_offset="1.0.0.0", udp_port=5353,
                      rampup_sec=5, enable_ipv6=False,
                      ipv6_client_msb="ff02::", ipv6_server_msb="ff03::"):
    """
    Build a parameterized UDP ASTFProfile.

    Uses ASTFProgram(stream=False) with send_msg/recv_msg for UDP datagram semantics.
    """
    from trex.astf.api import (ASTFProfile, ASTFTemplate, ASTFProgram,
                                ASTFTCPClientTemplate, ASTFTCPServerTemplate,
                                ASTFGlobalInfo, ASTFAssociationRule)

    msg_data  = b'x' * message_size
    resp_data = b'y' * message_size

    prog_c = ASTFProgram(stream=False)
    prog_s = ASTFProgram(stream=False)
    for _ in range(max(1, num_messages)):
        prog_c.send_msg(msg_data)
        prog_s.recv_msg(1)
        if server_wait_ms > 0:
            prog_s.delay(server_wait_ms * 1000)
        prog_s.send_msg(resp_data)
        prog_c.recv_msg(1)

    ip_gen = _build_ip_gen(client_ip_start, client_ip_end,
                           server_ip_start, server_ip_end, ip_offset)

    c_glob = ASTFGlobalInfo()
    c_glob.scheduler.rampup_sec = rampup_sec
    if enable_ipv6:
        c_glob.ipv6.src_msb = ipv6_client_msb
        c_glob.ipv6.dst_msb = ipv6_server_msb
        c_glob.ipv6.enable  = 1

    limit = max_flows if max_flows > 0 else None

    template = ASTFTemplate(
        client_template=ASTFTCPClientTemplate(
            program=prog_c,
            ip_gen=ip_gen,
            port=udp_port,
            cps=cps_base,
            limit=limit,
            cont=True
        ),
        server_template=ASTFTCPServerTemplate(
            program=prog_s,
            assoc=ASTFAssociationRule(port=udp_port)
        ),
        tg_name='udp-%d' % udp_port
    )

    return ASTFProfile(
        default_ip_gen=ip_gen,
        default_c_glob_info=c_glob,
        templates=template
    )


def build_mixed_profile(tcp_cps_base=int(ASTF_MULTIPLIER * 0.99),
                        udp_cps_base=max(1, int(ASTF_MULTIPLIER * 0.01)),
                        message_size=64, num_messages=1,
                        server_wait_ms=0, max_flows=0, tcp_mss=1400,
                        client_ip_start="16.0.0.0", client_ip_end="16.0.255.255",
                        server_ip_start="48.0.0.0", server_ip_end="48.0.255.255",
                        ip_offset="1.0.0.0", tcp_port=8080, udp_port=5353,
                        rampup_sec=5, enable_ipv6=False,
                        ipv6_client_msb="ff02::", ipv6_server_msb="ff03::"):
    """
    Build a mixed TCP+UDP ASTFProfile with two templates.

    Mirrors the generate_traffic_profile() function from cps_ndr.py.
    UDP template uses send_msg/recv_msg; TCP uses send/recv.
    """
    from trex.astf.api import (ASTFProfile, ASTFTemplate, ASTFProgram,
                                ASTFTCPClientTemplate, ASTFTCPServerTemplate,
                                ASTFGlobalInfo, ASTFAssociationRule)

    ip_gen = _build_ip_gen(client_ip_start, client_ip_end,
                           server_ip_start, server_ip_end, ip_offset)

    c_glob = ASTFGlobalInfo()
    c_glob.scheduler.rampup_sec = rampup_sec
    c_glob.tcp.mss = tcp_mss
    if enable_ipv6:
        c_glob.ipv6.src_msb = ipv6_client_msb
        c_glob.ipv6.dst_msb = ipv6_server_msb
        c_glob.ipv6.enable  = 1

    templates = []
    limit_total = max_flows if max_flows > 0 else None

    # UDP template
    if udp_cps_base > 0:
        msg_u  = b'x' * message_size
        resp_u = b'y' * message_size
        prog_uc = ASTFProgram(stream=False)
        prog_us = ASTFProgram(stream=False)
        for _ in range(max(1, num_messages)):
            prog_uc.send_msg(msg_u)
            prog_us.recv_msg(1)
            if server_wait_ms > 0:
                prog_us.delay(server_wait_ms * 1000)
            prog_us.send_msg(resp_u)
            prog_uc.recv_msg(1)
        limit_u = int(limit_total * udp_cps_base / (tcp_cps_base + udp_cps_base)) if limit_total else None
        templates.append(ASTFTemplate(
            client_template=ASTFTCPClientTemplate(
                program=prog_uc, ip_gen=ip_gen, port=udp_port,
                cps=udp_cps_base, limit=limit_u, cont=True
            ),
            server_template=ASTFTCPServerTemplate(
                program=prog_us, assoc=ASTFAssociationRule(port=udp_port)
            ),
            tg_name='udp-%d' % udp_port
        ))

    # TCP template
    if tcp_cps_base > 0:
        http_req  = b'x' * message_size
        http_resp = b'y' * message_size
        prog_tc = ASTFProgram(stream=True)
        prog_ts = ASTFProgram(stream=True)
        for _ in range(max(1, num_messages)):
            prog_tc.send(http_req)
            prog_ts.recv(message_size)
            if server_wait_ms > 0:
                prog_ts.delay(server_wait_ms * 1000)
            prog_ts.send(http_resp)
            prog_tc.recv(message_size)
        limit_t = int(limit_total * tcp_cps_base / (tcp_cps_base + udp_cps_base)) if limit_total else None
        templates.append(ASTFTemplate(
            client_template=ASTFTCPClientTemplate(
                program=prog_tc, ip_gen=ip_gen, port=tcp_port,
                cps=tcp_cps_base, limit=limit_t, cont=True
            ),
            server_template=ASTFTCPServerTemplate(
                program=prog_ts, assoc=ASTFAssociationRule(port=tcp_port)
            ),
            tg_name='tcp-%d' % tcp_port
        ))

    return ASTFProfile(
        default_ip_gen=ip_gen,
        default_c_glob_info=c_glob,
        templates=templates
    )


def load_astf_profile_file(profile_path):
    """
    Load an external ASTF Python profile file and return the ASTFProfile.

    The profile file must define a register() function that returns
    an object with a get_profile() method (standard TRex ASTF convention).

    Example profile file:
        from trex.astf.api import *
        class Prof1():
            def get_profile(self, tunables=[], **kwargs):
                ...
        def register():
            return Prof1()
    """
    spec = importlib.util.spec_from_file_location("astf_profile", profile_path)
    if spec is None:
        raise ImportError("Cannot load ASTF profile from: %s" % profile_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, 'register'):
        raise AttributeError("ASTF profile file '%s' must define register()" % profile_path)
    prof_obj = module.register()
    return prof_obj.get_profile()


def validate_ip_ranges(client_start, client_end, server_start, server_end):
    """
    Sanity-check that client and server IP ranges do not overlap and are valid.
    Raises ValueError with a descriptive message on failure.
    """
    def _ip_to_int(ip_str):
        parts = ip_str.split('.')
        if len(parts) != 4:
            raise ValueError("Invalid IPv4 address: %s" % ip_str)
        result = 0
        for p in parts:
            result = (result << 8) | int(p)
        return result

    cs = _ip_to_int(client_start)
    ce = _ip_to_int(client_end)
    ss = _ip_to_int(server_start)
    se = _ip_to_int(server_end)

    if cs > ce:
        raise ValueError("client_ip_start (%s) > client_ip_end (%s)" % (client_start, client_end))
    if ss > se:
        raise ValueError("server_ip_start (%s) > server_ip_end (%s)" % (server_start, server_end))

    # Check overlap
    if not (ce < ss or se < cs):
        raise ValueError(
            "Client IP range %s-%s overlaps with server IP range %s-%s" % (
                client_start, client_end, server_start, server_end))
