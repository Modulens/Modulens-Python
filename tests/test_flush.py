import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modulens.flush as _flush_submodule_import  # noqa: F401 - load the submodule

flush_mod = sys.modules["modulens.flush"]


class FlushDataTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "called_functions": {"mod.fn": {"count": 2, "total_time_sec": 0.01}},
            "dead_functions": [],
            "error_counts": {},
            "feature_flags": [],
        }

    def _patch_config(self, output: str):
        return mock.patch.dict(flush_mod.config, {"output": output}, clear=False)

    def test_file_mode_calls_file_only(self):
        with self._patch_config("file"), mock.patch.object(
            flush_mod.file_sink, "write", return_value=True
        ) as fw, mock.patch.object(flush_mod.http_sink, "send") as hs:
            self.assertTrue(flush_mod.flush_data(self.payload))
            fw.assert_called_once()
            hs.assert_not_called()

    def test_http_mode_calls_http_only(self):
        with self._patch_config("http"), mock.patch.object(
            flush_mod.file_sink, "write"
        ) as fw, mock.patch.object(
            flush_mod.http_sink, "send", return_value=True
        ) as hs:
            self.assertTrue(flush_mod.flush_data(self.payload))
            fw.assert_not_called()
            hs.assert_called_once()

    def test_both_mode_requires_both_sinks_ok(self):
        with self._patch_config("both"), mock.patch.object(
            flush_mod.file_sink, "write", return_value=True
        ), mock.patch.object(flush_mod.http_sink, "send", return_value=False):
            self.assertFalse(flush_mod.flush_data(self.payload))

    def test_file_failure_reported_in_file_mode(self):
        with self._patch_config("file"), mock.patch.object(
            flush_mod.file_sink, "write", return_value=False
        ):
            self.assertFalse(flush_mod.flush_data(self.payload))

    def test_http_failure_reported_in_http_mode(self):
        with self._patch_config("http"), mock.patch.object(
            flush_mod.http_sink, "send", return_value=False
        ):
            self.assertFalse(flush_mod.flush_data(self.payload))


if __name__ == "__main__":
    unittest.main()
