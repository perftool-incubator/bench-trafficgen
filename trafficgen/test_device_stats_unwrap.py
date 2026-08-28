#!/usr/bin/python3
# Runnable without pytest: python3 trafficgen/test_device_stats_unwrap.py

from __future__ import print_function

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tg_lib import UINT32_RANGE, unwrap_u32_counter


def _check(name, cond, detail=""):
     if cond:
          print("PASS: %s" % (name))
          return 0
     print("FAIL: %s %s" % (name, detail))
     return 1


def test_trial6_signed_wrap():
     """57d66cea trial 6: ipackets dumped as signed int32 of the same uint32 as opackets."""
     raw_tx = 3348214009
     raw_rx = -946753287
     runtime = 90.017015
     tx_pps = 37195345.89099628
     rx_pps = 37195345.89099628
     tx = unwrap_u32_counter(raw_tx, tx_pps * runtime)
     rx = unwrap_u32_counter(raw_rx, rx_pps * runtime)
     failures = 0
     failures += _check("trial6 tx k=0", tx['k'] == 0, "k=%s unwrapped=%s" % (tx['k'], tx['unwrapped']))
     failures += _check("trial6 rx signed_steps>=1", rx['signed_steps'] >= 1, "signed_steps=%s" % (rx['signed_steps']))
     failures += _check("trial6 rx k=0 after normalize", rx['k'] == 0, "k=%s" % (rx['k']))
     failures += _check("trial6 tx==rx after unwrap", tx['unwrapped'] == rx['unwrapped'],
                        "tx=%s rx=%s" % (tx['unwrapped'], rx['unwrapped']))
     failures += _check("trial6 zero loss", tx['unwrapped'] - rx['unwrapped'] == 0)
     return failures


def test_trial2_uint32_wrap():
     """57d66cea trial 2: 64-bit TX, RX = TX - 2^32. TRex rate fields still match."""
     raw_tx = 5568064168
     raw_rx = 1273068245
     runtime = 95.03387
     tx_pps = 58516000.0
     rx_pps = 58526000.0
     tx = unwrap_u32_counter(raw_tx, tx_pps * runtime)
     rx = unwrap_u32_counter(raw_rx, rx_pps * runtime)
     failures = 0
     failures += _check("trial2 tx k=0", tx['k'] == 0, "k=%s unwrapped=%s" % (tx['k'], tx['unwrapped']))
     failures += _check("trial2 rx k=1", rx['k'] == 1, "k=%s unwrapped=%s" % (rx['k'], rx['unwrapped']))
     failures += _check("trial2 rx unwrapped is raw+2^32",
                        rx['unwrapped'] == raw_rx + UINT32_RANGE,
                        "unwrapped=%s" % (rx['unwrapped']))
     residual = abs(tx['unwrapped'] - rx['unwrapped'])
     failures += _check("trial2 residual << 2^32", residual < 100000,
                        "residual=%s" % (residual))
     return failures


def test_trial7_noop():
     """57d66cea trial 7: counts already consistent, no wrap."""
     raw = 1674107005
     runtime = 90.018218
     pps = 18597424.412467264
     result = unwrap_u32_counter(raw, pps * runtime)
     failures = 0
     failures += _check("trial7 k=0", result['k'] == 0, "k=%s" % (result['k']))
     failures += _check("trial7 signed_steps=0", result['signed_steps'] == 0)
     failures += _check("trial7 unwrapped==raw", result['unwrapped'] == raw,
                        "unwrapped=%s" % (result['unwrapped']))
     return failures


def test_real_80pct_loss_not_unwrapped():
     """Genuine 80% loss: RX rate is low, so expected stays near the raw RX count."""
     runtime = 90.0
     tx_pps = 58.7e6
     rx_pps = 11.74e6
     raw_tx = int(round(tx_pps * runtime))
     raw_rx = int(round(rx_pps * runtime))
     tx = unwrap_u32_counter(raw_tx, tx_pps * runtime)
     rx = unwrap_u32_counter(raw_rx, rx_pps * runtime)
     loss_pct = 100.0 * (tx['unwrapped'] - rx['unwrapped']) / float(tx['unwrapped'])
     failures = 0
     failures += _check("real-loss rx k=0", rx['k'] == 0, "k=%s" % (rx['k']))
     failures += _check("real-loss tx k=0", tx['k'] == 0, "k=%s" % (tx['k']))
     failures += _check("real-loss stays ~80%", 79.0 <= loss_pct <= 81.0,
                        "loss_pct=%s" % (loss_pct))
     return failures


def test_jumbo_no_wrap():
     """9000B at 100G for 120s is well under 2^32 packets; unwrap must be a no-op."""
     runtime = 120.0
     pps = 1.38e6
     raw = int(round(pps * runtime))
     result = unwrap_u32_counter(raw, pps * runtime)
     failures = 0
     failures += _check("jumbo k=0", result['k'] == 0)
     failures += _check("jumbo unwrapped==raw", result['unwrapped'] == raw)
     return failures


def test_missing_expected():
     """No rate magnet: still fix signed dumps, do not invent wraps."""
     raw = -946753287
     result = unwrap_u32_counter(raw, None)
     failures = 0
     failures += _check("no-expected k=0", result['k'] == 0)
     failures += _check("no-expected signed normalize", result['unwrapped'] == raw + UINT32_RANGE,
                        "unwrapped=%s" % (result['unwrapped']))
     return failures


def test_high_loss_binary_search_expectation():
     """Verify the binary-search expectation calculation does not cause
     false unwrap when RX is low due to genuine DUT loss."""
     runtime = 90.0
     target_pps = 148.8e6
     tx_pps_snap = 148.0e6
     rx_pps_snap = 29.76e6

     raw_tx = int(round(tx_pps_snap * runtime))
     raw_rx = int(round(rx_pps_snap * runtime))

     # Fixed calculation (what binary-search.py should do):
     tx_expected = (tx_pps_snap * runtime) if tx_pps_snap > 0 else (target_pps * runtime)
     rx_expected = rx_pps_snap * runtime

     tx = unwrap_u32_counter(raw_tx, tx_expected)
     rx = unwrap_u32_counter(raw_rx, rx_expected)

     failures = 0
     failures += _check("high-loss-path rx k=0", rx['k'] == 0,
                        "k=%s (would be 2 with buggy max() floor)" % rx['k'])
     failures += _check("high-loss-path tx k=0", tx['k'] == 0,
                        "k=%s" % tx['k'])
     loss_pct = 100.0 * (tx['unwrapped'] - rx['unwrapped']) / float(tx['unwrapped'])
     failures += _check("high-loss-path preserves ~80% loss", 79.0 <= loss_pct <= 81.0,
                        "loss_pct=%s" % loss_pct)

     # Buggy calculation (confirms the old code would fail):
     buggy_rx_expected = max(rx_pps_snap * runtime, target_pps * runtime)
     buggy_rx = unwrap_u32_counter(raw_rx, buggy_rx_expected)
     failures += _check("high-loss-path buggy rx k>0 (confirms bug)", buggy_rx['k'] > 0,
                        "buggy k=%s (expected >0 to prove the bug)" % buggy_rx['k'])
     return failures


def test_saturation_tx_not_falsely_unwrapped():
     """TX at NIC ceiling (58 Mpps) but target is 100 Mpps.
     With buggy max() floor, TX would get a false +2^32 wrap."""
     runtime = 90.0
     target_pps = 100e6
     tx_pps_snap = 58e6
     raw_tx = int(round(tx_pps_snap * runtime))

     # Fixed path:
     tx_expected = (tx_pps_snap * runtime) if tx_pps_snap > 0 else (target_pps * runtime)
     tx = unwrap_u32_counter(raw_tx, tx_expected)
     failures = 0
     failures += _check("saturation-tx k=0", tx['k'] == 0,
                        "k=%s (would be 1 with buggy max() floor)" % tx['k'])
     failures += _check("saturation-tx unwrapped==raw", tx['unwrapped'] == raw_tx)

     # Buggy path:
     buggy_tx_expected = max(tx_pps_snap * runtime, target_pps * runtime)
     buggy_tx = unwrap_u32_counter(raw_tx, buggy_tx_expected)
     failures += _check("saturation-tx buggy k>0 (confirms bug)", buggy_tx['k'] > 0,
                        "buggy k=%s" % buggy_tx['k'])
     return failures


def main():
     failures = 0
     failures += test_trial6_signed_wrap()
     failures += test_trial2_uint32_wrap()
     failures += test_trial7_noop()
     failures += test_real_80pct_loss_not_unwrapped()
     failures += test_jumbo_no_wrap()
     failures += test_missing_expected()
     failures += test_high_loss_binary_search_expectation()
     failures += test_saturation_tx_not_falsely_unwrapped()
     if failures:
          print("%d check(s) failed" % (failures))
          return 1
     print("all checks passed")
     return 0


if __name__ == "__main__":
     sys.exit(main())
