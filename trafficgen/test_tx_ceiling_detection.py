#!/usr/bin/python3
# Runnable without pytest: python3 trafficgen/test_tx_ceiling_detection.py

from __future__ import print_function

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tg_lib import (detect_tx_ceiling, ceiling_to_rate_pct,
                    negative_packet_exceeds_tolerance, tx_rate_outside_tolerance,
                    TX_CEILING_CONSISTENCY_TOLERANCE, TX_CEILING_MIN_OBSERVATIONS)


def _check(name, cond, detail=""):
     if cond:
          print("PASS: %s" % (name))
          return 0
     print("FAIL: %s %s" % (name, detail))
     return 1


def test_first_observation():
     """First observation should set the ceiling but not confirm it."""
     ceiling, obs = detect_tx_ceiling(58.5, None, 0)
     failures = 0
     failures += _check("first obs ceiling", abs(ceiling - 58.5) < 0.001,
                         "got %s" % ceiling)
     failures += _check("first obs count", obs == 1, "got %d" % obs)
     return failures


def test_consistent_observation():
     """Two consistent observations should confirm the ceiling."""
     ceiling, obs = detect_tx_ceiling(58.5, None, 0)
     ceiling, obs = detect_tx_ceiling(58.3, ceiling, obs)
     failures = 0
     failures += _check("consistent obs count", obs == 2, "got %d" % obs)
     failures += _check("consistent ceiling max", ceiling == 58.5,
                         "got %s" % ceiling)
     return failures


def test_inconsistent_resets():
     """A wildly different observation should reset the counter."""
     ceiling, obs = detect_tx_ceiling(58.5, None, 0)
     ceiling, obs = detect_tx_ceiling(30.0, ceiling, obs)
     failures = 0
     failures += _check("inconsistent resets count", obs == 1, "got %d" % obs)
     failures += _check("inconsistent resets ceiling", ceiling == 30.0,
                         "got %s" % ceiling)
     return failures


def test_three_observations():
     """Three consistent observations should all increment."""
     ceiling, obs = detect_tx_ceiling(58.0, None, 0)
     ceiling, obs = detect_tx_ceiling(58.2, ceiling, obs)
     ceiling, obs = detect_tx_ceiling(57.8, ceiling, obs)
     failures = 0
     failures += _check("three obs count", obs == 3, "got %d" % obs)
     failures += _check("three obs keeps max", ceiling == 58.2,
                         "got %s" % ceiling)
     return failures


def test_ceiling_to_rate_pct_e810():
     """E810 at 64B: line rate ~148.8 Mpps, ceiling ~58 Mpps = ~39%."""
     # At rate=100%, target_mpps = line_rate = 148.8
     result = ceiling_to_rate_pct(58.5, 148.8, 100.0)
     failures = 0
     failures += _check("e810 ceiling pct", abs(result - 39.31) < 0.1,
                         "got %s" % result)
     return failures


def test_ceiling_to_rate_pct_at_50pct():
     """When running at 50%, target = line_rate * 0.5 = 74.4 Mpps."""
     result = ceiling_to_rate_pct(58.5, 74.4, 50.0)
     failures = 0
     # line_rate = 74.4 / 0.5 = 148.8, ceiling_pct = 58.5/148.8*100 = 39.31
     failures += _check("50pct ceiling pct", abs(result - 39.31) < 0.1,
                         "got %s" % result)
     return failures


def test_ceiling_to_rate_pct_invalid():
     """Zero target or rate should return None."""
     failures = 0
     failures += _check("zero target", ceiling_to_rate_pct(58.5, 0, 100.0) is None)
     failures += _check("zero rate", ceiling_to_rate_pct(58.5, 148.8, 0) is None)
     return failures


def test_scenario_02da9ca1():
     """Reproduce the 02da9ca1 run: trials 2-5 hit ceiling at ~58.5 Mpps."""
     observations = [58.53, 58.71, 58.67, 58.53]
     ceiling = None
     obs = 0
     for mpps in observations:
          ceiling, obs = detect_tx_ceiling(mpps, ceiling, obs)

     failures = 0
     failures += _check("scenario ceiling confirmed", obs >= TX_CEILING_MIN_OBSERVATIONS,
                         "got obs=%d" % obs)
     failures += _check("scenario ceiling value", abs(ceiling - 58.71) < 0.01,
                         "got %s" % ceiling)

     pct = ceiling_to_rate_pct(ceiling, 148.8, 100.0)
     failures += _check("scenario ceiling pct ~39.5%", abs(pct - 39.45) < 0.5,
                         "got %s%%" % pct)
     return failures


def test_failure_gates():
     """Only rate-tolerance failures should qualify for ceiling detection."""
     failures = 0
     failures += _check("stream bias within tolerance",
                        not negative_packet_exceeds_tolerance(100, 102, 2))
     failures += _check("stream bias over tolerance",
                        negative_packet_exceeds_tolerance(100, 103, 2))
     failures += _check("rate tolerance pass",
                        not tx_rate_outside_tolerance(58.0, 58.0, 5))
     failures += _check("rate tolerance fail",
                        tx_rate_outside_tolerance(50.0, 58.0, 5))
     return failures




if __name__ == "__main__":
     total_failures = 0
     total_failures += test_first_observation()
     total_failures += test_consistent_observation()
     total_failures += test_inconsistent_resets()
     total_failures += test_three_observations()
     total_failures += test_ceiling_to_rate_pct_e810()
     total_failures += test_ceiling_to_rate_pct_at_50pct()
     total_failures += test_ceiling_to_rate_pct_invalid()
     total_failures += test_failure_gates()
     total_failures += test_scenario_02da9ca1()
     print("\n%d total failures" % total_failures)
     sys.exit(0 if total_failures == 0 else 1)
