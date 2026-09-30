#!/usr/bin/env python3
# -*- mode: python; indent-tabs-mode: nil; python-indent-level: 4 -*-
# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

import importlib.util
import sys
import types
import unittest
from pathlib import Path


def load_post_processor():
    toolbox = types.ModuleType("toolbox")
    cdm_metrics = types.ModuleType("toolbox.cdm_metrics")
    cdm_metrics.CDMMetrics = object
    toolbox_json = types.ModuleType("toolbox.json")
    toolbox_json.load_json_file = object()
    toolbox_json.save_json_file = object()
    sys.modules["toolbox"] = toolbox
    sys.modules["toolbox.cdm_metrics"] = cdm_metrics
    sys.modules["toolbox.json"] = toolbox_json

    path = Path(__file__).parents[1] / "trafficgen-post-process.py"
    spec = importlib.util.spec_from_file_location("trafficgen_post_process", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AggregationDescriptorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.post_processor = load_post_processor()

    def test_explicit_constraint_survives_descriptor_build(self):
        metric = next(
            metric
            for metric in self.post_processor.TRIAL_LATENCY_METRICS
            if metric["type"] == "latency-stddev-usec"
        )

        desc = self.post_processor.build_metric_desc(metric, "test-source")

        self.assertEqual(desc["disallowed-aggregations"], ["sum"])

    def test_latency_and_percentage_default_to_sum_restriction(self):
        for metric_class in ("latency", "percentage"):
            with self.subTest(metric_class=metric_class):
                desc = self.post_processor.build_metric_desc(
                    {
                        "class": metric_class,
                        "type": "test-metric",
                        "default-aggregation": "avg",
                    },
                    "test-source",
                )
                self.assertEqual(desc["disallowed-aggregations"], ["sum"])


if __name__ == "__main__":
    unittest.main()
