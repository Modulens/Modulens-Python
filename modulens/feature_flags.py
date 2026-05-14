import functools
import inspect
import json
import threading
from collections import defaultdict

from .config import config
from .constants import (
    MAX_DISTINCT_VARIANTS_PER_FLAG,
    MAX_DISTINCT_VARIANTS_PER_FLAG_CAP,
    MAX_VARIANT_KEY_LEN,
    MAX_VARIANT_KEY_LEN_CAP,
    MIN_DISTINCT_VARIANTS_PER_FLAG,
    MIN_VARIANT_KEY_LEN,
    OVERFLOW_VARIANT_KEY,
    VARIANT_FALSE,
    VARIANT_KEY_TRUNCATE_ELLIPSIS_LEN,
    VARIANT_NULL,
    VARIANT_TRUE,
)


def _max_variant_key_len() -> int:
    raw = config.get("feature_flag_max_variant_len", MAX_VARIANT_KEY_LEN)
    try:
        return max(MIN_VARIANT_KEY_LEN, min(int(raw), MAX_VARIANT_KEY_LEN_CAP))
    except (TypeError, ValueError):
        return MAX_VARIANT_KEY_LEN


def _max_distinct_variants() -> int:
    raw = config.get("feature_flag_max_distinct_variants", MAX_DISTINCT_VARIANTS_PER_FLAG)
    try:
        return max(MIN_DISTINCT_VARIANTS_PER_FLAG, min(int(raw), MAX_DISTINCT_VARIANTS_PER_FLAG_CAP))
    except (TypeError, ValueError):
        return MAX_DISTINCT_VARIANTS_PER_FLAG


def serialize_variant(value) -> str:
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

    limit = _max_variant_key_len()
    if len(key) > limit:
        return key[: limit - VARIANT_KEY_TRUNCATE_ELLIPSIS_LEN] + "..."
    return key


class FeatureFlagRecorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._counts = defaultdict(lambda: defaultdict(int))

    def record(self, flag_name: str, function_name: str, value) -> None:
        variant = serialize_variant(value)
        key = (flag_name, function_name)
        with self._lock:
            variants = self._counts[key]
            if variant not in variants and len(variants) >= _max_distinct_variants():
                variant = OVERFLOW_VARIANT_KEY
            variants[variant] += 1

    def snapshot(self):
        with self._lock:
            rows = []
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

    def clear(self):
        with self._lock:
            self._counts.clear()


default_recorder = FeatureFlagRecorder()


def feature_flag(name=None):
    """
    Decorate a function to record successful return values as feature-flag variants.

    Exceptions are not counted. The logical flag name defaults to the function name.
    """

    def decorate(fn):
        flag_name = name if name is not None else fn.__name__
        function_name = f"{fn.__module__}.{fn.__qualname__}"

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                result = await fn(*args, **kwargs)
                default_recorder.record(flag_name, function_name, result)
                return result

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            default_recorder.record(flag_name, function_name, result)
            return result

        return sync_wrapper

    if callable(name):
        return decorate(name)
    return decorate
