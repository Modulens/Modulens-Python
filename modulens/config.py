import os

from .constants import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_EXCLUDE_MODULES,
    DEFAULT_FLUSH_INTERVAL_SEC,
    DEFAULT_MODULENS_API_URL,
    DEFAULT_OUTPUT_MODE,
)


def _safe_float(val, default):
    try:
        result = float(val)
        return result if result > 0 else default
    except (TypeError, ValueError):
        return default

config = {
    "include": [],
    "exclude": list(DEFAULT_EXCLUDE_MODULES),
    "flush_interval": _safe_float(os.getenv("MODULENS_FLUSH_INTERVAL"), DEFAULT_FLUSH_INTERVAL_SEC),
    "api_url": os.getenv("MODULENS_API_URL", DEFAULT_MODULENS_API_URL).rstrip("/"),
    "api_key": os.getenv("MODULENS_API_KEY", ""),
    "project_id": os.getenv("MODULENS_PROJECT_ID", ""),
    "environment": os.getenv("MODULENS_ENVIRONMENT", DEFAULT_ENVIRONMENT),
    "output": os.getenv("MODULENS_OUTPUT", DEFAULT_OUTPUT_MODE).lower(),
    "output_path": os.getenv("MODULENS_OUTPUT_PATH", "").strip(),
    "feature_flag_max_variant_len": os.getenv("MODULENS_FEATURE_FLAG_MAX_VARIANT_LEN", ""),
    "feature_flag_max_distinct_variants": os.getenv("MODULENS_FEATURE_FLAG_MAX_DISTINCT_VARIANTS", ""),
}
