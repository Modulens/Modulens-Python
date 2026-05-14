"""Modulens profiler: interpreter-level call profiling with periodic flush."""
from __future__ import annotations

import atexit
import inspect
import random
import site
import sys
import sysconfig
import threading
import time
from collections import defaultdict
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from .config import config
from .constants import (
    AVG_TIME_MS_DECIMALS,
    CALL_STARTS_MAX,
    DEFAULT_FLUSH_INTERVAL_SEC,
    DEFAULT_SAMPLE_RATE,
    DURATION_SEC_DECIMALS,
    FLUSH_THREAD_JOIN_TIMEOUT_SEC,
    MS_PER_SEC,
    PROFILE_EXCEPTION_TRACEBACK_INDEX,
    PROFILE_EXCEPTION_TUPLE_MIN_LEN,
    TOTAL_TIME_SEC_DECIMALS,
)
from .feature_flags import default_recorder
from .flush import flush_data

STDLIB_PATH = sysconfig.get_paths().get("stdlib", "")
SITE_PACKAGES: Set[str] = set(site.getsitepackages())
VENV_PREFIXES = [p for p in sys.path if "site-packages" in p or "venv" in p or "env" in p]

_THIRDPARTY_SUBSTRINGS = ("site-packages", "dist-packages", "/lib/python", "\\lib\\python")

_warned_once = False
_warn_lock = threading.Lock()


def _warn_once(msg: str) -> None:
    global _warned_once
    with _warn_lock:
        if _warned_once:
            return
        _warned_once = True
    sys.stderr.write(f"[modulens] profile handler error: {msg}\n")


class ModulensProfiler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.call_counts: Dict[str, int] = defaultdict(int)
        self.call_durations: Dict[str, float] = defaultdict(float)
        self.error_counts: Dict[str, int] = defaultdict(int)
        self.start_time = time.time()
        self.included: Set[str] = set()
        self.excluded: Set[str] = set(config.get("exclude", []))
        self.observed_modules: Set[str] = set()
        self.sample_rate = DEFAULT_SAMPLE_RATE
        self.flush_interval = config.get("flush_interval", DEFAULT_FLUSH_INTERVAL_SEC)
        self._flush_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._initialized = False
        self._track_cache: Dict[str, bool] = {}
        # Hot-path caches keyed by `id(code)` (stable for the process):
        self._code_track_cache: Dict[int, bool] = {}
        self._code_key_cache: Dict[int, str] = {}
        self._call_starts: Dict[int, float] = {}
        self._included_tuple: Tuple[str, ...] = ()
        self._excluded_tuple: Tuple[str, ...] = tuple(self.excluded)

    def _is_third_party_or_stdlib(self, filename: str) -> bool:
        if not filename:
            return True
        if STDLIB_PATH and filename.startswith(STDLIB_PATH):
            return True
        for needle in _THIRDPARTY_SUBSTRINGS:
            if needle in filename:
                return True
        return filename.startswith(sys.prefix)

    def _should_track_module(self, modname: str, filename: str) -> bool:
        if not modname:
            return False
        cached = self._track_cache.get(modname)
        if cached is not None:
            return cached
        if not filename:
            self._track_cache[modname] = False
            return False
        if self._included_tuple:
            if not any(modname.startswith(p) for p in self._included_tuple):
                self._track_cache[modname] = False
                return False
        if any(modname.startswith(p) for p in self._excluded_tuple):
            self._track_cache[modname] = False
            return False
        if self._is_third_party_or_stdlib(filename):
            self._track_cache[modname] = False
            return False
        self.observed_modules.add(modname)
        self._track_cache[modname] = True
        return True

    def _resolve_code(self, frame: Any) -> Optional[str]:
        """Return the cached func_key for this code object, or None if untracked."""
        code = frame.f_code
        cid = id(code)
        cached_key = self._code_key_cache.get(cid)
        if cached_key is not None:
            return cached_key
        tracked = self._code_track_cache.get(cid)
        if tracked is False:
            return None

        modname = frame.f_globals.get("__name__", "__main__")
        if not self._should_track_module(modname, code.co_filename):
            self._code_track_cache[cid] = False
            return None

        key = f"{modname}.{code.co_name}"
        self._code_key_cache[cid] = key
        self._code_track_cache[cid] = True
        return key

    def _profile_handler(self, frame: Any, event: str, arg: Any) -> None:
        try:
            if event == "call":
                key = self._resolve_code(frame)
                if key is None:
                    return
                if self.sample_rate < DEFAULT_SAMPLE_RATE and random.random() > self.sample_rate:
                    return
                fid = id(frame)
                now = time.perf_counter()
                with self._lock:
                    self.call_counts[key] += 1
                    self._call_starts[fid] = now
                    if len(self._call_starts) > CALL_STARTS_MAX:
                        self._call_starts.clear()

            elif event == "return":
                fid = id(frame)
                with self._lock:
                    start = self._call_starts.pop(fid, None)
                if start is None:
                    return
                key = self._resolve_code(frame)
                if key is None:
                    return
                elapsed = time.perf_counter() - start
                with self._lock:
                    self.call_durations[key] += elapsed

            elif event == "exception":
                fid = id(frame)
                with self._lock:
                    if fid not in self._call_starts:
                        return
                if (
                    arg
                    and len(arg) >= PROFILE_EXCEPTION_TUPLE_MIN_LEN
                    and arg[PROFILE_EXCEPTION_TRACEBACK_INDEX] is not None
                ):
                    tb = arg[PROFILE_EXCEPTION_TRACEBACK_INDEX]
                    if tb.tb_next is not None:
                        return
                key = self._resolve_code(frame)
                if key is None:
                    return
                with self._lock:
                    self.error_counts[key] += 1
                    self._call_starts.pop(fid, None)
        except Exception as e:  # narrow + warn-once to avoid hiding bugs
            _warn_once(repr(e))

    def _apply_profiler(self) -> None:
        sys.setprofile(self._profile_handler)
        threading.setprofile(self._profile_handler)

    def _start_flush_loop(self) -> None:
        def loop() -> None:
            while not self._stop_event.wait(self.flush_interval):
                try:
                    self.flush(report=False)
                except Exception as e:
                    _warn_once(repr(e))

        self._flush_thread = threading.Thread(target=loop, daemon=True)
        self._flush_thread.start()

    def _remove_profiler(self) -> None:
        """Stop profiling: clear sys and threading profilers."""
        sys.setprofile(None)
        threading.setprofile(None)

    def _shutdown(self) -> None:
        """Atexit handler: stop flush loop and do final flush."""
        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=FLUSH_THREAD_JOIN_TIMEOUT_SEC)
        self.flush(report=True)
        self._remove_profiler()

    def stop(self, report: bool = True) -> None:
        """Stop profiling: final flush, stop flush loop, remove profiler, unregister atexit."""
        if not self._initialized:
            return
        try:
            atexit.unregister(self._shutdown)
        except Exception:
            pass
        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=FLUSH_THREAD_JOIN_TIMEOUT_SEC)
        self.flush(report=report)
        self._remove_profiler()
        self._initialized = False

    def _get_defined_functions(self) -> Set[str]:
        funcs: Set[str] = set()
        for modname in self.observed_modules:
            try:
                mod = sys.modules.get(modname)
                if mod is None:
                    continue
                for name, obj in inspect.getmembers(mod, inspect.isfunction):
                    if getattr(obj, "__module__", None) != modname:
                        continue
                    code = getattr(obj, "__code__", None)
                    if code is None:
                        continue
                    fn = code.co_filename
                    if not fn:
                        continue
                    if (
                        STDLIB_PATH and fn.startswith(STDLIB_PATH)
                    ) or any(fn.startswith(p) for p in SITE_PACKAGES) or any(
                        fn.startswith(p) for p in VENV_PREFIXES
                    ):
                        continue
                    funcs.add(f"{modname}.{name}")
            except Exception as e:
                _warn_once(repr(e))
        return funcs

    def _reset_after_flush(self) -> None:
        """Reset counts and start time so next flush is for a new interval (not cumulative)."""
        with self._lock:
            self.call_counts.clear()
            self.call_durations.clear()
            self.error_counts.clear()
            self._call_starts.clear()
            default_recorder.clear()
            self.start_time = time.time()

    def flush(self, report: bool = True) -> None:
        with self._lock:
            duration = time.time() - self.start_time
            counts_snapshot = dict(self.call_counts)
            durations_snapshot = dict(self.call_durations)
            errors_snapshot = dict(self.error_counts)

        used = set(counts_snapshot.keys())
        all_funcs = self._get_defined_functions()
        unused = sorted(all_funcs - used)

        out: Dict[str, Any] = {
            "duration_sec": round(duration, DURATION_SEC_DECIMALS),
            "called_functions": {},
            "dead_functions": unused,
            "defined_functions": sorted(all_funcs),
            "error_counts": errors_snapshot,
            "feature_flags": default_recorder.snapshot(),
        }
        for key, cnt in counts_snapshot.items():
            tot = durations_snapshot.get(key, 0.0)
            avg_ms = (tot / cnt * MS_PER_SEC) if cnt else 0.0
            out["called_functions"][key] = {
                "count": cnt,
                "total_time_sec": round(tot, TOTAL_TIME_SEC_DECIMALS),
                "avg_time_ms": round(avg_ms, AVG_TIME_MS_DECIMALS),
            }
        ok = flush_data(out, report=report)
        if ok:
            self._reset_after_flush()

    def start(
        self,
        include: Optional[Iterable[str]] = None,
        exclude: Optional[Iterable[str]] = None,
        sample_rate: float = DEFAULT_SAMPLE_RATE,
    ) -> None:
        if self._initialized:
            return

        self.sample_rate = sample_rate
        self.flush_interval = config.get("flush_interval", self.flush_interval)
        if include:
            self.included = set(include)
            self._included_tuple = tuple(self.included)
        if exclude:
            self.excluded.update(exclude)
            self._excluded_tuple = tuple(self.excluded)
        self._track_cache.clear()
        self._code_track_cache.clear()
        self._code_key_cache.clear()

        self._apply_profiler()
        atexit.register(self._shutdown)
        self._start_flush_loop()
        self._initialized = True


default_profiler = ModulensProfiler()
start = default_profiler.start
stop = default_profiler.stop
flush = default_profiler.flush
