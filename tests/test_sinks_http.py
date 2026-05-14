import io
import os
import sys
import unittest
import urllib.error
from http import HTTPStatus
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulens.sinks import http as http_sink


CONFIGURED_ENV = {
    "api_url": "https://example.com",
    "api_key": "key",
    "project_id": "proj",
}


class _FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class UnretryableHelperTests(unittest.TestCase):
    def test_5xx_is_retryable(self):
        self.assertFalse(http_sink._is_unretryable_client_error(503))

    def test_4xx_is_unretryable(self):
        self.assertTrue(http_sink._is_unretryable_client_error(401))

    def test_429_is_retryable(self):
        self.assertFalse(http_sink._is_unretryable_client_error(HTTPStatus.TOO_MANY_REQUESTS))

    def test_none_is_retryable(self):
        self.assertFalse(http_sink._is_unretryable_client_error(None))


class SendTests(unittest.TestCase):
    def setUp(self):
        # Always reset module state so warn-once does not leak across tests.
        http_sink.last_error = None
        http_sink._warned_once = False
        self._stderr_patch = mock.patch.object(http_sink.sys, "stderr")
        self._stderr_patch.start()
        self.addCleanup(self._stderr_patch.stop)

    def _patched_config(self, **overrides):
        cfg = dict(CONFIGURED_ENV)
        cfg.update(overrides)
        return mock.patch.dict(http_sink.config, cfg, clear=False)

    def test_skips_when_credentials_missing(self):
        with mock.patch.dict(
            http_sink.config,
            {"api_url": "", "api_key": "", "project_id": ""},
            clear=False,
        ):
            self.assertTrue(http_sink.send({"payload": True}))

    def test_success_returns_true_and_clears_error(self):
        http_sink.last_error = "stale"
        with self._patched_config(), mock.patch.object(
            http_sink.urllib.request, "urlopen", return_value=_FakeResponse(200)
        ):
            self.assertTrue(http_sink.send({"x": 1}))
        self.assertIsNone(http_sink.last_error)

    def test_non_2xx_response_returns_false(self):
        sleeps = []
        with self._patched_config(), mock.patch.object(
            http_sink.urllib.request, "urlopen", return_value=_FakeResponse(503)
        ), mock.patch.object(http_sink.time, "sleep", side_effect=lambda s: sleeps.append(s)):
            result = http_sink.send({"x": 1})
        self.assertFalse(result)
        self.assertEqual(http_sink.last_error, "HTTP 503")
        # Retried MAX_HTTP_RETRIES times → MAX_HTTP_RETRIES sleeps recorded.
        self.assertEqual(len(sleeps), http_sink.MAX_HTTP_RETRIES)

    def test_4xx_breaks_without_retry(self):
        err = urllib.error.HTTPError(
            "https://example.com", 401, "Unauthorized", hdrs=None, fp=io.BytesIO()
        )
        sleeps = []
        with self._patched_config(), mock.patch.object(
            http_sink.urllib.request, "urlopen", side_effect=err
        ), mock.patch.object(http_sink.time, "sleep", side_effect=lambda s: sleeps.append(s)):
            result = http_sink.send({"x": 1})
        self.assertFalse(result)
        self.assertEqual(sleeps, [])

    def test_429_does_retry(self):
        err = urllib.error.HTTPError(
            "https://example.com", 429, "Too Many Requests", hdrs=None, fp=io.BytesIO()
        )
        sleeps = []
        with self._patched_config(), mock.patch.object(
            http_sink.urllib.request, "urlopen", side_effect=err
        ), mock.patch.object(http_sink.time, "sleep", side_effect=lambda s: sleeps.append(s)):
            self.assertFalse(http_sink.send({"x": 1}))
        self.assertEqual(len(sleeps), http_sink.MAX_HTTP_RETRIES)

    def test_url_error_retries(self):
        sleeps = []
        with self._patched_config(), mock.patch.object(
            http_sink.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ), mock.patch.object(http_sink.time, "sleep", side_effect=lambda s: sleeps.append(s)):
            self.assertFalse(http_sink.send({"x": 1}))
        self.assertEqual(len(sleeps), http_sink.MAX_HTTP_RETRIES)
        self.assertIn("connection refused", http_sink.last_error or "")

    def test_warn_once_only_writes_to_stderr_first_time(self):
        # Bypass the class-level stderr mock so we can count writes here.
        self._stderr_patch.stop()
        with self._patched_config(), mock.patch.object(
            http_sink.urllib.request, "urlopen", return_value=_FakeResponse(503)
        ), mock.patch.object(http_sink.time, "sleep"), mock.patch.object(
            http_sink.sys, "stderr"
        ) as stderr:
            http_sink.send({"x": 1})
            http_sink.send({"x": 1})
        self.assertEqual(stderr.write.call_count, 1)
        # Restart so cleanup does not double-stop.
        self._stderr_patch.start()


if __name__ == "__main__":
    unittest.main()
