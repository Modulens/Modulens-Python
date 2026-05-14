"""Modulens runtime configuration; reads environment once at import."""
from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

from .constants import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_EXCLUDE_MODULES,
    DEFAULT_FLUSH_INTERVAL_SEC,
    DEFAULT_MODULENS_API_URL,
    DEFAULT_OUTPUT_MODE,
)


def _safe_float(val: Optional[Any], default: float) -> float:
    try:
        result = float(val)
        return result if result > 0 else default
    except (TypeError, ValueError):
        return default


def build_config(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Build a fresh config dict from an environment-like mapping.

    Tests use this to exercise env parsing without reloading the module
    (which would invalidate `from .config import config` bindings elsewhere).
    """
    if env is None:
        env = os.environ
    return {
        "include": [],
        "exclude": list(DEFAULT_EXCLUDE_MODULES),
        "flush_interval": _safe_float(env.get("MODULENS_FLUSH_INTERVAL"), DEFAULT_FLUSH_INTERVAL_SEC),
        "api_url": env.get("MODULENS_API_URL", DEFAULT_MODULENS_API_URL).rstrip("/"),
        "api_key": env.get("MODULENS_API_KEY", ""),
        "project_id": env.get("MODULENS_PROJECT_ID", ""),
        "environment": env.get("MODULENS_ENVIRONMENT", DEFAULT_ENVIRONMENT),
        "output": env.get("MODULENS_OUTPUT", DEFAULT_OUTPUT_MODE).lower(),
        "output_path": env.get("MODULENS_OUTPUT_PATH", "").strip(),
        "feature_flag_max_variant_len": env.get("MODULENS_FEATURE_FLAG_MAX_VARIANT_LEN", ""),
        "feature_flag_max_distinct_variants": env.get("MODULENS_FEATURE_FLAG_MAX_DISTINCT_VARIANTS", ""),
    }


config: Dict[str, Any] = build_config()
