import asyncio
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulens import feature_flag
from modulens.constants import (
    DISTINCT_VARIANTS_DEFAULT,
    DISTINCT_VARIANTS_MAX,
    DISTINCT_VARIANTS_MIN,
    OVERFLOW_VARIANT_KEY,
    VARIANT_KEY_LEN_DEFAULT,
    VARIANT_KEY_LEN_MAX,
    VARIANT_KEY_LEN_MIN,
)
from modulens.feature_flags import (
    FeatureFlagRecorder,
    _clamp,
    _limits,
    _read_int_limit,
    default_recorder,
    refresh_limits,
    serialize_variant,
)


class HelperTests(unittest.TestCase):
    def test_clamp_within_bounds(self):
        self.assertEqual(_clamp(50, 0, 100), 50)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-5, 0, 100), 0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(200, 0, 100), 100)

    def test_read_int_limit_invalid_falls_back(self):
        self.assertEqual(
            _read_int_limit("__missing_key__", default=10, lo=1, hi=20),
            10,
        )


class SerializeVariantTests(unittest.TestCase):
    def test_primitives(self):
        self.assertEqual(serialize_variant(None), "null")
        self.assertEqual(serialize_variant(True), "true")
        self.assertEqual(serialize_variant(False), "false")
        self.assertEqual(serialize_variant(42), "42")
        self.assertEqual(serialize_variant(3.14), "3.14")
        self.assertEqual(serialize_variant("variant_a"), "variant_a")

    def test_bytes_use_str(self):
        self.assertEqual(serialize_variant(b"abc"), "b'abc'")

    def test_collection_uses_sorted_json(self):
        self.assertEqual(
            serialize_variant({"b": 2, "a": 1}),
            '{"a":1,"b":2}',
        )
        self.assertEqual(serialize_variant([1, 2, 3]), "[1,2,3]")

    def test_unserializable_object_falls_back_to_str(self):
        class Obj:
            def __str__(self) -> str:
                return "obj_repr"

        self.assertIn("obj_repr", serialize_variant(Obj()))

    def test_truncates_long_strings(self):
        original_cap = _limits.variant_key_len
        try:
            _limits.variant_key_len = 16
            result = serialize_variant("a" * 100)
            self.assertEqual(len(result), 16)
            self.assertTrue(result.endswith("..."))
        finally:
            _limits.variant_key_len = original_cap


class RecorderTests(unittest.TestCase):
    def setUp(self):
        default_recorder.clear()

    def test_snapshot_excludes_empty_buckets(self):
        recorder = FeatureFlagRecorder()
        self.assertEqual(recorder.snapshot(), [])

    def test_record_aggregates_per_flag_and_function(self):
        recorder = FeatureFlagRecorder()
        recorder.record("flag_a", "mod.fn_a", "x")
        recorder.record("flag_a", "mod.fn_a", "x")
        recorder.record("flag_a", "mod.fn_a", "y")
        recorder.record("flag_b", "mod.fn_b", True)

        rows = recorder.snapshot()
        self.assertEqual([r["flag_name"] for r in rows], ["flag_a", "flag_b"])
        self.assertEqual(rows[0]["variants"], {"x": 2, "y": 1})
        self.assertEqual(rows[1]["variants"], {"true": 1})

    def test_clear_empties_state(self):
        recorder = FeatureFlagRecorder()
        recorder.record("flag", "fn", "x")
        recorder.clear()
        self.assertEqual(recorder.snapshot(), [])

    def test_overflow_routes_extras_into_other_bucket(self):
        recorder = FeatureFlagRecorder()
        original_cap = _limits.distinct_variants
        try:
            _limits.distinct_variants = 3
            for i in range(7):
                recorder.record("flag", "fn", f"v_{i}")
        finally:
            _limits.distinct_variants = original_cap

        rows = recorder.snapshot()
        self.assertEqual(len(rows), 1)
        variants = rows[0]["variants"]
        self.assertIn(OVERFLOW_VARIANT_KEY, variants)
        # First three keep their own buckets; the remaining four collapse into overflow.
        own_buckets = [v for k, v in variants.items() if k != OVERFLOW_VARIANT_KEY]
        self.assertEqual(sum(own_buckets), 3)
        self.assertEqual(variants[OVERFLOW_VARIANT_KEY], 4)

    def test_record_is_thread_safe(self):
        recorder = FeatureFlagRecorder()

        def worker():
            for _ in range(200):
                recorder.record("flag", "fn", "v")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        rows = recorder.snapshot()
        self.assertEqual(rows[0]["variants"]["v"], 4 * 200)


class DecoratorTests(unittest.TestCase):
    def setUp(self):
        default_recorder.clear()

    def test_records_successful_returns(self):
        @feature_flag("pricing_experiment")
        def resolve_price():
            return "variant_a"

        resolve_price()
        resolve_price()
        rows = default_recorder.snapshot()
        self.assertEqual(rows[0]["variants"]["variant_a"], 2)

    def test_default_flag_name_is_function_name(self):
        @feature_flag()
        def my_flag():
            return True

        my_flag()
        rows = default_recorder.snapshot()
        self.assertEqual(rows[0]["flag_name"], "my_flag")

    def test_bare_decorator_works(self):
        @feature_flag
        def some_flag():
            return "on"

        some_flag()
        rows = default_recorder.snapshot()
        self.assertEqual(rows[0]["flag_name"], "some_flag")
        self.assertEqual(rows[0]["variants"]["on"], 1)

    def test_exception_does_not_record(self):
        @feature_flag("api_version")
        def health_payload():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            health_payload()
        self.assertEqual(default_recorder.snapshot(), [])

    def test_async_function_records(self):
        @feature_flag("async_flag")
        async def load():
            return "on"

        asyncio.run(load())
        rows = default_recorder.snapshot()
        self.assertEqual(rows[0]["variants"]["on"], 1)


class LimitsRefreshTests(unittest.TestCase):
    def test_refresh_respects_min_max(self):
        from modulens import config as config_module

        original = dict(config_module.config)
        try:
            config_module.config["feature_flag_max_variant_len"] = 1  # too low → MIN
            config_module.config["feature_flag_max_distinct_variants"] = 9_999  # too high → MAX
            refresh_limits()
            self.assertEqual(_limits.variant_key_len, VARIANT_KEY_LEN_MIN)
            self.assertEqual(_limits.distinct_variants, DISTINCT_VARIANTS_MAX)
        finally:
            config_module.config.clear()
            config_module.config.update(original)
            refresh_limits()
            self.assertEqual(_limits.variant_key_len, VARIANT_KEY_LEN_DEFAULT)
            self.assertEqual(_limits.distinct_variants, DISTINCT_VARIANTS_DEFAULT)


if __name__ == "__main__":
    unittest.main()
