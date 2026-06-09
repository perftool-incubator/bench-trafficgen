#!/usr/bin/env python3
# -*- mode: python; indent-tabs-mode: nil; python-indent-level: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

import os
import sys
from pathlib import Path

TOOLBOX_HOME = os.environ.get("TOOLBOX_HOME")
if TOOLBOX_HOME:
    sys.path.append(str(Path(TOOLBOX_HOME) / "python"))

from toolbox.cdm_metrics import CDMMetrics
from toolbox.json import load_json_file, save_json_file

TRIAL_METRICS = [
    {
        "key": "flubberbubbles",
        "class": "pass/fail",
        "type": "trial-result",
        "altkey": "result",
        "altvalue": "status",
    },
]

TRIAL_STATS_DEVICE_METRICS = [
    {"key": "rx", "field": "rx_latency_maximum", "class": "count", "type": "max-roundtrip-usec"},
    {"key": "rx", "field": "rx_latency_average", "class": "count", "type": "mean-roundtrip-usec"},
    {"key": "tx", "field": "tx_l2_bps", "class": "throughput", "type": "l2-tx-bps"},
    {"key": "tx", "field": "tx_l1_bps", "class": "throughput", "type": "l1-tx-bps"},
    {"key": "rx", "field": "rx_l2_bps", "class": "throughput", "type": "l2-rx-bps"},
    {"key": "rx", "field": "rx_l1_bps", "class": "throughput", "type": "l1-rx-bps"},
    {"key": "rx", "field": "rx_pps", "class": "throughput", "type": "rx-pps"},
    {"key": "tx", "field": "tx_pps", "class": "throughput", "type": "tx-pps"},
    {"key": "rx", "field": "rx_lost_pps", "class": "throughput", "type": "lost-rx-pps"},
]

TRIAL_PROFILER_METRICS = [
    {"key": "tsdelta", "subkey": "", "field": "", "class": "count", "type": "tsdelta", "extra_field": "", "cumulative": False},
    {"key": "global", "subkey": "rx", "field": "pps", "class": "throughput", "type": "rx-pps", "extra_field": "", "cumulative": False},
    {"key": "global", "subkey": "tx", "field": "pps", "class": "throughput", "type": "tx-pps", "extra_field": "", "cumulative": False},
    {"key": "global", "subkey": "rx", "field": "bps", "class": "throughput", "type": "rx-bps", "extra_field": "", "cumulative": False},
    {"key": "global", "subkey": "tx", "field": "bps", "class": "throughput", "type": "tx-bps", "extra_field": "", "cumulative": False},
    {"key": "global", "subkey": "rx", "field": "drop_bps", "class": "throughput", "type": "rx-drop-bps", "extra_field": "", "cumulative": False},
    {"key": "global", "subkey": "misc", "field": "cpu_util", "class": "count", "type": "tx-cpu-util", "extra_field": "", "cumulative": False},
    {"key": "global", "subkey": "rx", "field": "cpu_util", "class": "count", "type": "rx-cpu-util", "extra_field": "", "cumulative": False},
    {"key": "global", "subkey": "misc", "field": "bw_per_core", "class": "throughput", "type": "per-core-Gbps", "extra_field": "", "cumulative": False},
    {"key": "global", "subkey": "misc", "field": "queue_full", "class": "throughput", "type": "queue-full-per-second", "extra_field": "", "cumulative": True},
    {"key": "ports", "subkey": "rx", "field": "pps", "class": "throughput", "type": "port-rx-pps", "extra_field": "rx_port", "cumulative": False},
    {"key": "ports", "subkey": "tx", "field": "pps", "class": "throughput", "type": "port-tx-pps", "extra_field": "tx_port", "cumulative": False},
    {"key": "ports", "subkey": "rx", "field": "bps_l1", "class": "throughput", "type": "rx-l1-bps", "extra_field": "rx_port", "cumulative": False},
    {"key": "ports", "subkey": "tx", "field": "bps_l1", "class": "throughput", "type": "tx-l1-bps", "extra_field": "tx_port", "cumulative": False},
    {"key": "ports", "subkey": "rx", "field": "bps", "class": "throughput", "type": "rx-l2-bps", "extra_field": "rx_port", "cumulative": False},
    {"key": "ports", "subkey": "tx", "field": "bps", "class": "throughput", "type": "tx-l2-bps", "extra_field": "tx_port", "cumulative": False},
    {"key": "ports", "subkey": "rx", "field": "util", "class": "count", "type": "rx-port-util", "extra_field": "rx_port", "cumulative": False},
    {"key": "ports", "subkey": "tx", "field": "util", "class": "count", "type": "tx-port-util", "extra_field": "tx_port", "cumulative": False},
    {"key": "pgids", "subkey": "latency", "field": "average", "class": "count", "type": "mean-round-trip-usec", "extra_field": "stream", "cumulative": False},
    {"key": "pgids", "subkey": "latency", "field": "total_max", "class": "count", "type": "max-round-trip-usec", "extra_field": "stream", "cumulative": False},
    {"key": "pgids", "subkey": "latency", "field": "total_min", "class": "count", "type": "min-round-trip-usec", "extra_field": "stream", "cumulative": False},
    {"key": "pgids", "subkey": "latency", "field": "duplicate", "class": "throughput", "type": "duplicate-latency-pps", "extra_field": "stream", "cumulative": True},
    {"key": "pgids", "subkey": "latency", "field": "dropped", "class": "throughput", "type": "dropped-latency-pps", "extra_field": "stream", "cumulative": True},
    {"key": "pgids", "subkey": "latency", "field": "out_of_order", "class": "throughput", "type": "out-of-order-latency-pps", "extra_field": "stream", "cumulative": True},
    {"key": "pgids", "subkey": "latency", "field": "seq_too_high", "class": "throughput", "type": "before-expected-latency-pps", "extra_field": "stream", "cumulative": True},
    {"key": "pgids", "subkey": "latency", "field": "seq_too_low", "class": "throughput", "type": "after-expected-latency-pps", "extra_field": "stream", "cumulative": True},
    {"key": "pgids", "subkey": "tx_pps", "field": "stream", "class": "throughput", "type": "stream-tx-pps", "extra_field": "tx_port", "cumulative": False},
    {"key": "pgids", "subkey": "rx_pps", "field": "stream", "class": "throughput", "type": "stream-rx-pps", "extra_field": "rx_port", "cumulative": False},
]


def process_profiler_data(trial, period_name, metrics):
    profiler_data = trial.get("profiler-data")
    if not profiler_data:
        return

    print("Found profiler data")
    source = "trafficgen-trex-profiler"

    trex_ports = set()
    trex_pgids = set()
    trex_latency_pgids = set()

    sorted_timestamps = sorted(profiler_data.keys(), key=lambda x: float(x))

    profiler_begin = None
    profiler_end = None

    for timestamp in sorted_timestamps:
        ts_data = profiler_data[timestamp]

        if profiler_begin is None:
            profiler_begin = int(float(timestamp))
        profiler_end = int(float(timestamp))

        for port in ts_data.get("ports", {}):
            if "total" in str(port):
                continue
            trex_ports.add(port)

        for pgid in ts_data.get("pgids", {}):
            trex_pgids.add(pgid)
            pgid_data = ts_data["pgids"][pgid]
            if pgid_data and "latency" in pgid_data:
                trex_latency_pgids.add(pgid)

    print(f"profiler_begin:{profiler_begin}")
    print(f"profiler_end:{profiler_end}")

    # fixup dropped latency packet counter -- sometimes a packet
    # is presumed dropped but then it shows up later so the
    # counter goes backwards
    print("Checking for dropped latency packet stats which need fixup:")
    for pgid in sorted(trex_latency_pgids, key=lambda x: int(x)):
        later_value = None
        later_timestamp = None
        for timestamp in sorted(sorted_timestamps, key=lambda x: float(x), reverse=True):
            ts_data = profiler_data[timestamp]
            pgid_data = (ts_data.get("pgids", {}).get(pgid) or {}).get("latency", {})
            if "dropped" in pgid_data:
                if later_value is not None:
                    if later_value < pgid_data["dropped"]:
                        print(f"pgid:{pgid} | timestamp:{timestamp} value:{pgid_data['dropped']} | later_timestamp:{later_timestamp} later_value:{later_value}")
                        pgid_data["dropped"] = later_value
                later_value = pgid_data["dropped"]
                later_timestamp = timestamp

    for pm in TRIAL_PROFILER_METRICS:
        print(f"metric: {pm['type']}")

        if pm["key"] in ("tsdelta", "global"):
            prev_timestamp = None
            for timestamp in sorted_timestamps:
                if prev_timestamp is not None:
                    value = -1
                    ts_float = float(timestamp)
                    prev_float = float(prev_timestamp)

                    if pm["key"] == "tsdelta":
                        value = profiler_data[timestamp].get("tsdelta", -1)
                    elif pm["key"] == "global":
                        value = profiler_data[timestamp].get("global", {}).get(pm["subkey"], {}).get(pm["field"], -1)
                        if pm["cumulative"] and ts_float != prev_float:
                            prev_val = profiler_data[prev_timestamp].get("global", {}).get(pm["subkey"], {}).get(pm["field"])
                            if prev_val is not None:
                                value -= prev_val
                                value /= (ts_float - prev_float)

                    desc = {"class": pm["class"], "source": source, "type": pm["type"]}
                    sample = {"end": int(ts_float), "begin": int(prev_float), "value": value}
                    metrics.log_sample(period_name, desc, {}, sample)

                prev_timestamp = timestamp

        elif pm["key"] == "ports":
            for port in sorted(trex_ports, key=lambda x: int(x)):
                prev_timestamp = None
                for timestamp in sorted_timestamps:
                    if prev_timestamp is not None:
                        ts_float = float(timestamp)
                        prev_float = float(prev_timestamp)
                        value = profiler_data[timestamp].get("ports", {}).get(port, {}).get(pm["subkey"], {}).get(pm["field"], -1)

                        if pm["cumulative"] and ts_float != prev_float:
                            prev_val = profiler_data[prev_timestamp].get("ports", {}).get(port, {}).get(pm["subkey"], {}).get(pm["field"])
                            if prev_val is not None:
                                value -= prev_val
                                value /= (ts_float - prev_float)

                        desc = {"class": pm["class"], "source": source, "type": pm["type"]}
                        sample = {"end": int(ts_float), "begin": int(prev_float), "value": value}
                        names = {pm["extra_field"]: port}
                        metrics.log_sample(period_name, desc, names, sample)

                    prev_timestamp = timestamp

        elif pm["key"] == "pgids" and pm["subkey"] == "latency":
            for pgid in sorted(trex_latency_pgids, key=lambda x: int(x)):
                prev_timestamp = None
                for timestamp in sorted_timestamps:
                    if prev_timestamp is not None:
                        ts_float = float(timestamp)
                        prev_float = float(prev_timestamp)
                        value = 0

                        pgid_data = (profiler_data[timestamp].get("pgids", {}).get(pgid) or {}).get("latency", {})
                        if pm["field"] in pgid_data:
                            value = pgid_data[pm["field"]]

                            if pm["cumulative"] and ts_float != prev_float:
                                prev_pgid_data = (profiler_data[prev_timestamp].get("pgids", {}).get(pgid) or {}).get("latency", {})
                                if pm["field"] in prev_pgid_data:
                                    value -= prev_pgid_data[pm["field"]]
                                    value /= (ts_float - prev_float)

                        desc = {"class": pm["class"], "source": source, "type": pm["type"]}
                        sample = {"end": int(ts_float), "begin": int(prev_float), "value": value}
                        names = {pm["extra_field"]: pgid}
                        metrics.log_sample(period_name, desc, names, sample)

                    prev_timestamp = timestamp

        elif pm["key"] == "pgids":
            for pgid in sorted(trex_pgids, key=lambda x: int(x)):
                for port in sorted(trex_ports, key=lambda x: int(x)):
                    prev_timestamp = None
                    for timestamp in sorted_timestamps:
                        if prev_timestamp is not None:
                            ts_float = float(timestamp)
                            prev_float = float(prev_timestamp)
                            value = 0

                            pgid_subkey = (profiler_data[timestamp].get("pgids", {}).get(pgid) or {}).get(pm["subkey"], {})
                            if port in pgid_subkey:
                                value = pgid_subkey[port]

                                if pm["cumulative"] and ts_float != prev_float:
                                    prev_pgid_subkey = (profiler_data[prev_timestamp].get("pgids", {}).get(pgid) or {}).get(pm["subkey"], {})
                                    if port in prev_pgid_subkey:
                                        value -= prev_pgid_subkey[port]
                                        value /= (ts_float - prev_float)

                            desc = {"class": pm["class"], "source": source, "type": pm["type"]}
                            sample = {"end": int(ts_float), "begin": int(prev_float), "value": value}
                            names = {pm["field"]: pgid, pm["extra_field"]: port}
                            metrics.log_sample(period_name, desc, names, sample)

                        prev_timestamp = timestamp


def main():
    rs_cs_label = os.environ.get("RS_CS_LABEL", "")
    if rs_cs_label.startswith("server-"):
        sys.exit(0)

    result_file = "binary-search.json.xz"
    if not os.path.exists(result_file):
        result_file = "binary-search.json"
        if not os.path.exists(result_file):
            print(f"Could not find binary-search.json[.xz] in directory {os.getcwd()}")
            sys.exit(1)

    bs_json, err = load_json_file(result_file, uselzma=result_file.endswith(".xz"))
    if bs_json is None:
        print(f"Failed to load {result_file}: {err}")
        sys.exit(1)

    periods = []
    trials = bs_json.get("trials", [])

    measurement_trial_index = -1
    for index in range(len(trials) - 1, -1, -1):
        trial = trials[index]
        if trial["trial_params"]["trial_mode"] == "validation":
            if trial["result"] == "pass" or trial["trial_params"].get("one_shot") == 1:
                measurement_trial_index = index
                break

    if measurement_trial_index == -1:
        print("Could not find measurement trial index, run failed")
    else:
        print(f"Found measurement trial index = {measurement_trial_index}")

    for index, trial in enumerate(trials):
        print(f"\nProcessing new period: Trial:{trial['trial']} Index:{index}")

        period_name = f"trial-{trial['trial']}"
        if index == measurement_trial_index:
            period_name = "measurement"
        print(f"period_name:{period_name}")

        trial_end = int(trial["stats"]["trial_stop"])
        trial_begin = int(trial["stats"]["trial_start"])
        print(f"trial_begin:{trial_begin}")
        print(f"trial_end:{trial_end}")

        metrics = CDMMetrics()

        for tm in TRIAL_METRICS:
            desc = {"class": tm["class"], "source": "trafficgen", "type": tm["type"]}
            if "altvalue" in tm and "altkey" in tm:
                desc["value-format"] = "status"
                metric_value = 1 if trial.get(tm["altkey"]) == "pass" else 0
            elif tm["key"] in trial:
                metric_value = trial[tm["key"]]
            else:
                metric_value = 0.0

            sample = {"end": trial_end, "begin": trial_begin, "value": metric_value}
            metrics.log_sample(period_name, desc, {}, sample)

        for dev_pair in trial["trial_params"].get("test_dev_pairs", []):
            for tsdm in TRIAL_STATS_DEVICE_METRICS:
                desc = {"class": tsdm["class"], "source": "trafficgen", "type": tsdm["type"]}
                value = trial["stats"].get(str(dev_pair[tsdm["key"]]), {}).get(tsdm["field"], 0)
                sample = {"end": trial_end, "begin": trial_begin, "value": value}
                names = {"tx_port": dev_pair["tx"], "rx_port": dev_pair["rx"], "port_pair": dev_pair["dev_pair"]}
                metrics.log_sample(period_name, desc, names, sample)

        process_profiler_data(trial, period_name, metrics)

        metric_data_name = metrics.finish_samples()
        periods.append({
            "name": period_name,
            "metric-files": [metric_data_name],
        })

    sample_data = {
        "rickshaw-bench-metric": {"schema": {"version": "2021.04.12"}},
        "benchmark": "trafficgen",
        "primary-period": "measurement",
        "primary-metric": "rx-pps",
        "periods": periods,
    }

    _, err = save_json_file("postprocess/post-process-data.json", sample_data)
    if err:
        print(f"Failed to write post-process-data.json: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
