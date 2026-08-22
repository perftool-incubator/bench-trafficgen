import sys
import json
import datetime
import ipaddress


def format_timestamp(ts):
    return (format_datetime(datetime.datetime.fromtimestamp(ts)))


def format_datetime(dt):
    return (dt.strftime("%Y-%m-%d %H:%M:%S.%f"))


def error (string):
    return("ERROR: %s" % (string))


def not_json_serializable(obj):
    try:
        return(obj.to_dictionary())
    except AttributeError:
        try:
            return("scapy:%s" % (obj.command()))
        except AttributeError:
            return(repr(obj))


def dump_json_readable(obj):
     return json.dumps(obj, indent = 4, separators=(',', ': '), sort_keys = False, default = not_json_serializable)


def dump_json_parsable(obj):
     return json.dumps(obj, separators=(',', ':'), default = not_json_serializable)


def commify(string):
     return str.format("{:,}", string)


def sec_to_usec(seconds):
    useconds = seconds * 1e6
    return(useconds)


def ip_to_int (ip):
    ip_fields = ip.split(".")
    if len(ip_fields) != 4:
         raise ValueError("IP addresses should be in the form of W.X.Y.Z")
    ip_int = 256**3 * int(ip_fields[0]) + 256**2 * int(ip_fields[1]) + 256**1 * int(ip_fields[2]) + int(ip_fields[3])
    return ip_int


def int_to_ip (_int):
    orig__int = _int

    octet = int(_int / (256**3))
    _int = _int - (octet * 256**3)
    ip = str(octet)

    octet = int(_int / (256**2))
    _int = _int - (octet * 256**2)
    ip = ip + "." + str(octet)

    octet = int(_int / (256**1))
    _int = _int - (octet * 256**1)
    ip = ip + "." + str(octet)

    octet = int(_int)
    _int = _int - octet
    ip = ip + "." + str(octet)

    if _int != 0:
        raise ValueError("Error converting integer %d to IP address (calculated '%s' with remainder %d)" % (orig__int, ip, _int))

    return ip


def is_ipv6 (ip):
    return ':' in str(ip)


def ipv6_to_int (ip):
    return int(ipaddress.IPv6Address(ip))


def int_to_ipv6 (_int):
    return str(ipaddress.IPv6Address(_int))


def ip_to_int_auto (ip):
    if is_ipv6(ip):
        return ipv6_to_int(ip)
    else:
        return ip_to_int(ip)


def int_to_ip_auto (_int, ipv6=False):
    if ipv6:
        return int_to_ipv6(_int)
    else:
        return int_to_ip(_int)


def calculate_latency_pps (dividend, divisor, total_rate, protocols):
     return int((float(dividend) / float(divisor) * total_rate / protocols))


# TRex device-stat packet counters on some NICs (ice/E810, i40e, ixgbe)
# are 32-bit. JSON may dump values above 2^31 as signed negatives.
UINT32_RANGE = 2 ** 32
DEVICE_STATS_UNWRAP_MAX_K = 4


def unwrap_u32_counter(raw, expected, max_wraps=DEVICE_STATS_UNWRAP_MAX_K):
     """Align a possibly wrapped 32-bit packet counter toward expected.

     Average TRex rate fields (tx_pps / rx_pps) do not wrap. Callers should
     pass expected = pps * runtime. The correction is packet-count based and
     does not depend on frame size.

     Real loss is preserved: if expected stays near the reported counter,
     k remains 0.

     Returns a dict with raw, expected, k, signed_steps, and unwrapped.
     k is the number of +2^32 steps after signed normalization, clamped to
     [0, max_wraps].
     """
     raw = int(raw)
     value = raw
     signed_steps = 0
     while value < 0 and signed_steps < max_wraps:
          value += UINT32_RANGE
          signed_steps += 1

     k = 0
     if expected is not None and expected > 0:
          k = int(round((float(expected) - float(value)) / float(UINT32_RANGE)))
          if k < 0:
               k = 0
          elif k > max_wraps:
               k = max_wraps
          value = value + (k * UINT32_RANGE)

     return {
          'raw': raw,
          'expected': expected,
          'k': k,
          'signed_steps': signed_steps,
          'unwrapped': value,
     }


TX_CEILING_CONSISTENCY_TOLERANCE = 0.10
TX_CEILING_MIN_OBSERVATIONS = 2


def detect_tx_ceiling(observed_mpps, current_ceiling_mpps, observations):
     """Update TX ceiling state with a new observation.

     Returns (ceiling_mpps, observations) tuple.  The ceiling is confirmed
     when observations >= TX_CEILING_MIN_OBSERVATIONS.
     """
     if current_ceiling_mpps is None:
          return (observed_mpps, 1)

     if abs(observed_mpps - current_ceiling_mpps) / current_ceiling_mpps < TX_CEILING_CONSISTENCY_TOLERANCE:
          return (max(current_ceiling_mpps, observed_mpps), observations + 1)

     return (observed_mpps, 1)


def ceiling_to_rate_pct(ceiling_mpps, target_mpps, rate_pct):
     """Convert a ceiling in Mpps to a percentage of line rate.

     target_mpps is the TX target for the current trial at rate_pct.
     Line rate = target_mpps / (rate_pct / 100).
     """
     if target_mpps <= 0 or rate_pct <= 0:
          return None
     line_rate_mpps = target_mpps / (rate_pct / 100.0)
     return (ceiling_mpps / line_rate_mpps) * 100.0


