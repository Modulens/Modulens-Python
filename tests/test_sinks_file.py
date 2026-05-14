import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulens.constants import DEFAULT_RUNTIME_REPORT_PATH
from modulens.sinks import file as file_sink


class OutputPathTests(unittest.TestCase):
    def test_uses_config_override(self):
        with mock.patch.dict(file_sink.config, {"output_path": "  custom.json  "}):
            self.assertEqual(file_sink.output_path(), "custom.json")

    def test_falls_back_to_default(self):
        with mock.patch.dict(file_sink.config, {"output_path": ""}):
            self.assertEqual(file_sink.output_path(), DEFAULT_RUNTIME_REPORT_PATH)


class LoadExistingTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing.json")
            self.assertEqual(file_sink._load_existing(path), [])

    def test_malformed_json_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not valid json")
            path = f.name
        try:
            self.assertEqual(file_sink._load_existing(path), [])
        finally:
            os.unlink(path)

    def test_non_list_payload_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"oops": "object"}, f)
            path = f.name
        try:
            self.assertEqual(file_sink._load_existing(path), [])
        finally:
            os.unlink(path)

    def test_oversized_file_resets(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([{"a": 1}], f)
            path = f.name
        try:
            with mock.patch.object(file_sink, "MAX_FILE_SIZE_BYTES", 1):
                self.assertEqual(file_sink._load_existing(path), [])
        finally:
            os.unlink(path)

    def test_trims_when_over_count(self):
        data = [{"i": i} for i in range(10)]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            with mock.patch.object(file_sink, "MAX_FILE_REPORTS", 6), mock.patch.object(
                file_sink, "FILE_REPORT_TRIM_DIVISOR", 2
            ):
                trimmed = file_sink._load_existing(path)
            # MAX_FILE_REPORTS // FILE_REPORT_TRIM_DIVISOR == 3, take from tail
            self.assertEqual(trimmed, data[-3:])
        finally:
            os.unlink(path)


class WriteTests(unittest.TestCase):
    def test_appends_to_existing_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out", "report.json")
            with mock.patch.dict(file_sink.config, {"output_path": path}):
                self.assertTrue(file_sink.write({"timestamp": 1}))
                self.assertTrue(file_sink.write({"timestamp": 2}))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual([entry["timestamp"] for entry in data], [1, 2])

    def test_returns_false_when_open_fails(self):
        with mock.patch.dict(file_sink.config, {"output_path": "ok.json"}), mock.patch(
            "builtins.open", side_effect=PermissionError("nope")
        ):
            self.assertFalse(file_sink.write({"timestamp": 1}))


if __name__ == "__main__":
    unittest.main()
