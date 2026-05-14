import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulens.config import _safe_float, build_config
from modulens.constants import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_EXCLUDE_MODULES,
    DEFAULT_FLUSH_INTERVAL_SEC,
    DEFAULT_MODULENS_API_URL,
    DEFAULT_OUTPUT_MODE,
)


class SafeFloatTests(unittest.TestCase):
    def test_positive_string_returns_value(self):
        self.assertEqual(_safe_float("12.5", 60.0), 12.5)

    def test_positive_int_returns_value(self):
        self.assertEqual(_safe_float(30, 60.0), 30.0)

    def test_zero_falls_back(self):
        self.assertEqual(_safe_float("0", 60.0), 60.0)

    def test_negative_falls_back(self):
        self.assertEqual(_safe_float("-5", 60.0), 60.0)

    def test_non_numeric_falls_back(self):
        self.assertEqual(_safe_float("abc", 60.0), 60.0)

    def test_none_falls_back(self):
        self.assertEqual(_safe_float(None, 60.0), 60.0)


class BuildConfigTests(unittest.TestCase):
    def test_defaults_with_empty_env(self):
        cfg = build_config({})
        self.assertEqual(cfg["flush_interval"], DEFAULT_FLUSH_INTERVAL_SEC)
        self.assertEqual(cfg["api_url"], DEFAULT_MODULENS_API_URL)
        self.assertEqual(cfg["api_key"], "")
        self.assertEqual(cfg["project_id"], "")
        self.assertEqual(cfg["environment"], DEFAULT_ENVIRONMENT)
        self.assertEqual(cfg["output"], DEFAULT_OUTPUT_MODE)
        self.assertEqual(cfg["output_path"], "")
        self.assertEqual(cfg["exclude"], list(DEFAULT_EXCLUDE_MODULES))
        self.assertEqual(cfg["include"], [])

    def test_env_overrides_apply(self):
        cfg = build_config(
            {
                "MODULENS_FLUSH_INTERVAL": "30",
                "MODULENS_API_URL": "https://example.com/",
                "MODULENS_API_KEY": "ml_x",
                "MODULENS_PROJECT_ID": "proj-1",
                "MODULENS_ENVIRONMENT": "staging",
                "MODULENS_OUTPUT": "FILE",
                "MODULENS_OUTPUT_PATH": "  reports.json  ",
            }
        )
        self.assertEqual(cfg["flush_interval"], 30.0)
        self.assertEqual(cfg["api_url"], "https://example.com")  # trailing slash stripped
        self.assertEqual(cfg["api_key"], "ml_x")
        self.assertEqual(cfg["project_id"], "proj-1")
        self.assertEqual(cfg["environment"], "staging")
        self.assertEqual(cfg["output"], "file")  # lowercased
        self.assertEqual(cfg["output_path"], "reports.json")  # stripped

    def test_invalid_flush_interval_falls_back(self):
        cfg = build_config({"MODULENS_FLUSH_INTERVAL": "not-a-number"})
        self.assertEqual(cfg["flush_interval"], DEFAULT_FLUSH_INTERVAL_SEC)


if __name__ == "__main__":
    unittest.main()
