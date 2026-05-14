import os
import sys
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulens.feature_flags import default_recorder, feature_flag
from modulens.profiler import ModulensProfiler, STDLIB_PATH


def _frame_like(modname: str, filename: str, name: str = "fn"):
    """Stand-in for a Python frame that the profiler can read attributes from."""
    code = types.SimpleNamespace(co_filename=filename, co_name=name)
    return types.SimpleNamespace(f_code=code, f_globals={"__name__": modname})


class IsThirdPartyTests(unittest.TestCase):
    def setUp(self):
        self.profiler = ModulensProfiler()

    def test_empty_filename(self):
        self.assertTrue(self.profiler._is_third_party_or_stdlib(""))

    def test_stdlib_path(self):
        if not STDLIB_PATH:
            self.skipTest("STDLIB_PATH unknown on this interpreter")
        self.assertTrue(self.profiler._is_third_party_or_stdlib(os.path.join(STDLIB_PATH, "x.py")))

    def test_site_packages(self):
        self.assertTrue(
            self.profiler._is_third_party_or_stdlib("/usr/lib/python3.12/site-packages/foo.py")
        )

    def test_user_code(self):
        # A path that does not contain stdlib/site-packages substrings.
        self.assertFalse(self.profiler._is_third_party_or_stdlib("/srv/app/handlers.py"))


class ShouldTrackModuleTests(unittest.TestCase):
    def setUp(self):
        self.profiler = ModulensProfiler()
        # Force a user-code-like filename across these tests.
        self.profiler._is_third_party_or_stdlib = lambda fn: False  # type: ignore[assignment]

    def test_caches_result(self):
        self.profiler._included_tuple = ("app",)
        self.assertTrue(self.profiler._should_track_module("app.sub", "/src/x.py"))
        self.assertTrue(self.profiler._track_cache["app.sub"])
        # Second call hits cache and remains True even if include changes
        self.profiler._included_tuple = ("nope",)
        self.assertTrue(self.profiler._should_track_module("app.sub", "/src/x.py"))

    def test_excluded_modules_skipped(self):
        self.profiler._excluded_tuple = ("app.private",)
        self.assertFalse(self.profiler._should_track_module("app.private.api", "/src/x.py"))

    def test_include_required_when_provided(self):
        self.profiler._included_tuple = ("svc",)
        self.assertFalse(self.profiler._should_track_module("other.mod", "/src/x.py"))

    def test_missing_filename_returns_false(self):
        self.assertFalse(self.profiler._should_track_module("app", ""))

    def test_missing_module_returns_false(self):
        self.assertFalse(self.profiler._should_track_module("", "/src/x.py"))


class ResolveCodeCacheTests(unittest.TestCase):
    def setUp(self):
        self.profiler = ModulensProfiler()
        # Track everything except real third-party paths.
        self.profiler._is_third_party_or_stdlib = lambda fn: False  # type: ignore[assignment]

    def test_first_call_populates_cache(self):
        frame = _frame_like("app.svc", "/src/svc.py", "do")
        key = self.profiler._resolve_code(frame)
        self.assertEqual(key, "app.svc.do")
        cid = id(frame.f_code)
        self.assertEqual(self.profiler._code_key_cache[cid], "app.svc.do")
        self.assertTrue(self.profiler._code_track_cache[cid])

    def test_untracked_code_caches_false_and_returns_none(self):
        self.profiler._included_tuple = ("only.this",)
        frame = _frame_like("app.svc", "/src/svc.py", "do")
        self.assertIsNone(self.profiler._resolve_code(frame))
        cid = id(frame.f_code)
        self.assertFalse(self.profiler._code_track_cache[cid])
        self.assertNotIn(cid, self.profiler._code_key_cache)


class DefinedFunctionsTests(unittest.TestCase):
    def test_imported_callables_excluded(self):
        profiler = ModulensProfiler()
        mod = types.ModuleType("example_app.helpers")
        mod.__file__ = __file__

        def checkout_config():
            return True

        checkout_config.__module__ = mod.__name__
        mod.checkout_config = checkout_config
        mod.feature_flag = feature_flag  # imported from another module

        sys.modules[mod.__name__] = mod
        try:
            profiler.observed_modules.add(mod.__name__)
            defined = profiler._get_defined_functions()
            self.assertIn("example_app.helpers.checkout_config", defined)
            self.assertNotIn("example_app.helpers.feature_flag", defined)
        finally:
            sys.modules.pop(mod.__name__, None)


class FlushPayloadTests(unittest.TestCase):
    def setUp(self):
        default_recorder.clear()

    def test_flush_resets_counters_when_sink_succeeds(self):
        profiler = ModulensProfiler()
        profiler.call_counts["mod.fn"] = 3
        profiler.call_durations["mod.fn"] = 0.030
        profiler.error_counts["mod.fn"] = 1

        captured = {}

        def fake_flush(payload, report=True):
            captured["payload"] = payload
            return True

        with mock.patch("modulens.profiler.flush_data", side_effect=fake_flush):
            profiler.flush()

        out = captured["payload"]
        self.assertIn("mod.fn", out["called_functions"])
        self.assertEqual(out["called_functions"]["mod.fn"]["count"], 3)
        self.assertEqual(out["called_functions"]["mod.fn"]["total_time_sec"], 0.03)
        self.assertEqual(out["error_counts"], {"mod.fn": 1})
        self.assertEqual(profiler.call_counts, {})  # reset

    def test_flush_does_not_reset_when_sink_fails(self):
        profiler = ModulensProfiler()
        profiler.call_counts["mod.fn"] = 7

        with mock.patch("modulens.profiler.flush_data", return_value=False):
            profiler.flush()

        self.assertEqual(profiler.call_counts["mod.fn"], 7)


class ProfileHandlerErrorTests(unittest.TestCase):
    def test_handler_swallows_unexpected_errors_and_warns_once(self):
        profiler = ModulensProfiler()
        # Force `_resolve_code` to raise to exercise the broad guard.
        profiler._resolve_code = mock.Mock(side_effect=RuntimeError("boom"))  # type: ignore[assignment]

        with mock.patch("modulens.profiler._warn_once") as warner:
            profiler._profile_handler(_frame_like("app", "/src/x.py"), "call", None)
            profiler._profile_handler(_frame_like("app", "/src/x.py"), "call", None)
        # Should be invoked twice (warn-once is checked inside _warn_once, not here);
        # we only verify the handler did not raise and called the warn helper.
        self.assertGreaterEqual(warner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
