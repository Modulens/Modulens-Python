import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulens.constants import DEFAULT_ENVIRONMENT
from modulens.report import build_ingest_payload, build_report


class BuildReportTests(unittest.TestCase):
    def test_empty_payload_returns_minimal_report(self):
        report = build_report({})
        self.assertIn("timestamp", report)
        self.assertEqual(report["called_functions"], {})
        self.assertEqual(report["dead_functions"], [])
        self.assertNotIn("feature_flags", report)  # only present when non-empty

    def test_called_functions_computes_avg_time_ms(self):
        payload = {
            "called_functions": {
                "mod.fn": {"count": 4, "total_time_sec": 0.020},
            },
            "dead_functions": [],
            "error_counts": {"mod.fn": 2},
        }
        report = build_report(payload)
        fn = report["called_functions"]["mod.fn"]
        self.assertEqual(fn["count"], 4)
        self.assertEqual(fn["error_count"], 2)
        self.assertAlmostEqual(fn["avg_time_ms"], 5.0)

    def test_zero_count_yields_zero_avg(self):
        payload = {
            "called_functions": {"mod.fn": {"count": 0, "total_time_sec": 0.0}},
            "dead_functions": [],
            "error_counts": {},
        }
        report = build_report(payload)
        self.assertEqual(report["called_functions"]["mod.fn"]["avg_time_ms"], 0.0)

    def test_dead_functions_sorted(self):
        report = build_report({"dead_functions": ["b", "a", "c"], "called_functions": {}})
        self.assertEqual(report["dead_functions"], ["a", "b", "c"])

    def test_feature_flags_pass_through_when_non_empty(self):
        flags = [{"flag_name": "f", "function_name": "fn", "variants": {"v": 1}}]
        report = build_report(
            {"feature_flags": flags, "called_functions": {}, "dead_functions": []}
        )
        self.assertEqual(report["feature_flags"], flags)


class BuildIngestPayloadTests(unittest.TestCase):
    def test_defaults_pull_from_config(self):
        report = {
            "timestamp": 1000,
            "called_functions": {"x": {"count": 1}},
            "dead_functions": ["y"],
        }
        with mock.patch.dict(
            "modulens.report.config",
            {"environment": "staging", "project_id": "proj-1"},
            clear=False,
        ):
            payload = build_ingest_payload(report)
        self.assertEqual(payload["timestamp"], 1000)
        self.assertEqual(payload["environment"], "staging")
        self.assertEqual(payload["project_id"], "proj-1")
        self.assertEqual(payload["called_functions"], {"x": {"count": 1}})
        self.assertEqual(payload["dead_functions"], ["y"])
        self.assertNotIn("feature_flags", payload)

    def test_environment_falls_back_to_default(self):
        with mock.patch.dict("modulens.report.config", {}, clear=True):
            payload = build_ingest_payload(
                {"timestamp": 1, "called_functions": {}, "dead_functions": []}
            )
        self.assertEqual(payload["environment"], DEFAULT_ENVIRONMENT)
        self.assertEqual(payload["project_id"], "")

    def test_feature_flags_only_when_present(self):
        report = {
            "timestamp": 1,
            "called_functions": {},
            "dead_functions": [],
            "feature_flags": [{"flag_name": "f", "function_name": "fn", "variants": {}}],
        }
        payload = build_ingest_payload(report)
        self.assertIn("feature_flags", payload)


if __name__ == "__main__":
    unittest.main()
