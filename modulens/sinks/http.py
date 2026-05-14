"""HTTP ingest sink with bounded retries."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from typing import Any, Dict, Optional

from ..config import config
from ..constants import (
    HTTP_REQUEST_TIMEOUT_SEC,
    HTTP_RETRY_DELAY_SEC,
    INGEST_ENDPOINT,
    MAX_HTTP_RETRIES,
)


last_error: Optional[str] = None
_warned_once = False
_warn_lock = threading.Lock()


def _warn_once(msg: str) -> None:
    global _warned_once
    with _warn_lock:
        if _warned_once:
            return
        _warned_once = True
    sys.stderr.write(f"[modulens] ingest failed: {msg}\n")


def _is_unretryable_client_error(code: Optional[int]) -> bool:
    if code is None:
        return False
    return (
        HTTPStatus.BAD_REQUEST <= code < HTTPStatus.INTERNAL_SERVER_ERROR
        and code != HTTPStatus.TOO_MANY_REQUESTS
    )


def send(payload: Dict[str, Any]) -> bool:
    """POST payload to Modulens ingest API. Returns True on success or when skipped."""
    global last_error

    api_url = (config.get("api_url") or "").strip()
    api_key = (config.get("api_key") or "").strip()
    project_id = (config.get("project_id") or "").strip()
    if not api_url or not api_key or not project_id:
        return True

    url = f"{api_url.rstrip('/')}{INGEST_ENDPOINT}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
    )

    error: Optional[str] = None
    for attempt in range(MAX_HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_REQUEST_TIMEOUT_SEC) as resp:
                if HTTPStatus.OK <= resp.status < HTTPStatus.MULTIPLE_CHOICES:
                    last_error = None
                    return True
                error = f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            error = f"HTTP {e.code}: {e.reason}"
            if _is_unretryable_client_error(e.code):
                break
        except urllib.error.URLError as e:
            error = str(e.reason or e)
        except Exception as e:
            error = str(e)
        if attempt < MAX_HTTP_RETRIES:
            time.sleep(HTTP_RETRY_DELAY_SEC * (attempt + 1))

    last_error = error
    if error:
        _warn_once(error)
    return False
