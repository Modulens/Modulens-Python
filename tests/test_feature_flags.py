import asyncio
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulens import feature_flag
from modulens.constants import OVERFLOW_VARIANT_KEY
from modulens.feature_flags import default_recorder, serialize_variant
from modulens.flush import _build_report


class FeatureFlagTests(unittest.TestCase):
    def setUp(self):
        default_recorder.clear()

    def test_serialize_primitives(self):
        self.assertEqual(serialize_variant(None), "null")
        self.assertEqual(serialize_variant(True), "true")
        self.assertEqual(serialize_variant(False), "false")
        self.assertEqual(serialize_variant("v2"), "v2")

    def test_decorator_records_successful_returns(self):
        @feature_flag("pricing_experiment")
        def resolve_price():
            return "variant_a"

        resolve_price()
        resolve_price()

        rows = default_recorder.snapshot()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["flag_name"], "pricing_experiment")
        self.assertEqual(rows[0]["variants"]["variant_a"], 2)

    def test_exceptions_are_not_recorded(self):
        @feature_flag("api_version")
        def health_payload():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            health_payload()

        self.assertEqual(default_recorder.snapshot(), [])

    def test_build_report_includes_feature_flags(self):
        @feature_flag("new_checkout_ui")
        def get_checkout_config():
            return False

        get_checkout_config()
        report = _build_report(
            {
                "dead_functions": [],
                "called_functions": {},
                "error_counts": {},
                "feature_flags": default_recorder.snapshot(),
            }
        )
        self.assertEqual(len(report["feature_flags"]), 1)
        self.assertEqual(report["feature_flags"][0]["variants"]["false"], 1)

    def test_overflow_bucket_when_too_many_variants(self):
        with patch("modulens.feature_flags._max_distinct_variants", return_value=4):
            for i in range(10):
                default_recorder.record("many_return_buckets", "app.fn", f"bucket_{i}")

        rows = default_recorder.snapshot()
        self.assertEqual(len(rows), 1)
        self.assertIn(OVERFLOW_VARIANT_KEY, rows[0]["variants"])

    def test_async_decorator(self):
        @feature_flag("async_flag")
        async def load():
            return "on"

        asyncio.run(load())
        rows = default_recorder.snapshot()
        self.assertEqual(rows[0]["variants"]["on"], 1)


if __name__ == "__main__":
    unittest.main()
