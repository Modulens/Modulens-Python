"""Feature-flag variant recording for Modulens."""
from __future__ import annotations

import functools
import inspect
import json
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from .config import config
from .constants import (
    DISTINCT_VARIANTS_DEFAULT,
    DISTINCT_VARIANTS_MAX,
    DISTINCT_VARIANTS_MIN,
    OVERFLOW_VARIANT_KEY,
    VARIANT_FALSE,
    VARIANT_KEY_LEN_DEFAULT,
    VARIANT_KEY_LEN_MAX,
    VARIANT_KEY_LEN_MIN,
    VARIANT_KEY_TRUNCATE_ELLIPSIS_LEN,
    VARIANT_NULL,
    VARIANT_TRUE,
)


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def _read_int_limit(key: str, default: int, lo: int, hi: int) -> int:
    raw = config.get(key, default)
    try:
        return _clamp(int(raw), lo, hi)
    except (TypeError, ValueError):
        return default


class _Limits:
    """Cached caps so hot-path serialization does not touch config every call."""

    __slots__ = ("variant_key_len", "distinct_variants")

    def __init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.variant_key_len = _read_int_limit(
            "feature_flag_max_variant_len",
            VARIANT_KEY_LEN_DEFAULT,
            VARIANT_KEY_LEN_MIN,
            VARIANT_KEY_LEN_MAX,
        )
        self.distinct_variants = _read_int_limit(
            "feature_flag_max_distinct_variants",
            DISTINCT_VARIANTS_DEFAULT,
            DISTINCT_VARIANTS_MIN,
            DISTINCT_VARIANTS_MAX,
        )


_limits = _Limits()


def refresh_limits() -> None:
    """Re-read feature-flag caps from config. Call after changing config at runtime."""
    _limits.refresh()


def serialize_variant(value: Any) -> str:
    """Serialize a successful return value into a stable bucket key."""
    if value is None:
        key = VARIANT_NULL
    elif isinstance(value, bool):
        key = VARIANT_TRUE if value else VARIANT_FALSE
    elif isinstance(value, (int, float, str, bytes, bytearray)):
        key = str(value)
    else:
        try:
            key = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            key = str(value)

    limit = _limits.variant_key_len
    if len(key) > limit:
        return key[: limit - VARIANT_KEY_TRUNCATE_ELLIPSIS_LEN] + "..."
    return key


class FeatureFlagRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Dict[tuple, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record(self, flag_name: str, function_name: str, value: Any) -> None:
        variant = serialize_variant(value)
        key = (flag_name, function_name)
        cap = _limits.distinct_variants
        with self._lock:
            variants = self._counts[key]
            if variant not in variants and len(variants) >= cap:
                variant = OVERFLOW_VARIANT_KEY
            variants[variant] += 1

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows: List[Dict[str, Any]] = []
            for (flag_name, function_name), variants in self._counts.items():
                if not variants:
                    continue
                rows.append(
                    {
                        "flag_name": flag_name,
                        "function_name": function_name,
                        "variants": dict(variants),
                    }
                )
        rows.sort(key=lambda row: (row["flag_name"], row["function_name"]))
        return rows

    def clear(self) -> None:
        with self._lock:
            self._counts.clear()


default_recorder = FeatureFlagRecorder()


def feature_flag(name: Optional[str] = None) -> Callable[..., Any]:
    """
    Decorate a function to record successful return values as feature-flag variants.

    Exceptions are not counted. The logical flag name defaults to the function name.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        flag_name = name if name is not None else fn.__name__
        function_name = f"{fn.__module__}.{fn.__qualname__}"
        record = default_recorder.record

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                result = await fn(*args, **kwargs)
                record(flag_name, function_name, result)
                return result

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = fn(*args, **kwargs)
            record(flag_name, function_name, result)
            return result

        return sync_wrapper

    if callable(name):
        fn = name
        return decorate(fn)
    return decorate
