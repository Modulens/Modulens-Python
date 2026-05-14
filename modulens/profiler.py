import sys
import threading
import time
import atexit
import inspect
import site
import sysconfig
import random
from collections import defaultdict
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
SITE_PACKAGES = set(site.getsitepackages())
VENV_PREFIXES = [p for p in sys.path if "site-packages" in p or "venv" in p or "env" in p]

class ModulensProfiler:
    def __init__(self):
        self._lock = threading.Lock()
        self.call_counts = defaultdict(int)
        self.call_durations = defaultdict(float)
        self.error_counts = defaultdict(int)
        self.start_time = time.time()
        self.included = set()
        self.excluded = set(config.get("exclude", []))
        self.observed_modules = set()
        self.sample_rate = DEFAULT_SAMPLE_RATE
        self.flush_interval = config.get("flush_interval", DEFAULT_FLUSH_INTERVAL_SEC)
        self._flush_thread = None
        self._stop_event = threading.Event()
        self._initialized = False
        self._track_cache = {}
        self._call_starts = {}
        self._included_tuple = ()
        self._excluded_tuple = tuple(self.excluded)

    def _is_third_party_or_stdlib(self, filename):
        if not filename:
            return True
        return (
            filename.startswith(STDLIB_PATH)
            or "site-packages" in filename
            or "dist-packages" in filename
            or "/lib/python" in filename
            or "\\lib\\python" in filename
            or filename.startswith(sys.prefix)  # covers venv base path
        )

    def _should_track(self, frame):
        mod = frame.f_globals.get("__name__")
        if not mod:
            return False

        cached = self._track_cache.get(mod)
        if cached is not None:
            return cached

        fn = frame.f_code.co_filename
        if not fn:
            self._track_cache[mod] = False
            return False

        if self._included_tuple:
            if not any(mod.startswith(p) for p in self._included_tuple):
                self._track_cache[mod] = False
                return False
        if any(mod.startswith(p) for p in self._excluded_tuple):
            self._track_cache[mod] = False
            return False

        if self._is_third_party_or_stdlib(fn):
            self._track_cache[mod] = False
            return False

        self.observed_modules.add(mod)
        self._track_cache[mod] = True
        return True

    def _func_key(self, frame):
        return f"{frame.f_globals.get('__name__', '__main__')}.{frame.f_code.co_name}"

    def _profile_handler(self, frame, event, arg):
        try:
            if event == "call":
                if not self._should_track(frame):
                    return
                if self.sample_rate < DEFAULT_SAMPLE_RATE and random.random() > self.sample_rate:
                    return
                key = self._func_key(frame)
                with self._lock:
                    self.call_counts[key] += 1
                    self._call_starts[id(frame)] = time.perf_counter()
                    if len(self._call_starts) > CALL_STARTS_MAX:
                        self._call_starts.clear()

            elif event == "return":
                with self._lock:
                    start = self._call_starts.pop(id(frame), None)
                if start is not None:
                    key = self._func_key(frame)
                    elapsed = time.perf_counter() - start
                    with self._lock:
                        self.call_durations[key] += elapsed

            elif event == "exception":
                fid = id(frame)
                with self._lock:
                    if fid not in self._call_starts:
                        return
                if arg and len(arg) >= PROFILE_EXCEPTION_TUPLE_MIN_LEN and arg[PROFILE_EXCEPTION_TRACEBACK_INDEX] is not None:
                    tb = arg[PROFILE_EXCEPTION_TRACEBACK_INDEX]
                    if tb.tb_next is not None:
                        return
                key = self._func_key(frame)
                with self._lock:
                    self.error_counts[key] += 1
                    self._call_starts.pop(fid, None)
        except Exception:
            pass

    def _apply_profiler(self):
        sys.setprofile(self._profile_handler)
        threading.setprofile(self._profile_handler)

    def _start_flush_loop(self):
        def loop():
            while not self._stop_event.wait(self.flush_interval):
                try:
                    self.flush(report=False)
                except Exception:
                    pass
        self._flush_thread = threading.Thread(target=loop, daemon=True)
        self._flush_thread.start()

    def _remove_profiler(self):
        """Stop profiling: clear sys and threading profilers."""
        sys.setprofile(None)
        threading.setprofile(None)

    def _shutdown(self):
        """Atexit handler: stop flush loop and do final flush."""
        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=FLUSH_THREAD_JOIN_TIMEOUT_SEC)
        self.flush(report=True)
        self._remove_profiler()

    def stop(self, report=True):
        """
        Stop profiling: final flush, stop flush loop, remove profiler, unregister atexit.
        Safe to call multiple times; no-op if not started.
        """
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

    def _get_defined_functions(self):
        funcs = set()
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
                    if not fn or fn.startswith(STDLIB_PATH) or any(fn.startswith(p) for p in SITE_PACKAGES) or any(fn.startswith(p) for p in VENV_PREFIXES):
                        continue
                    funcs.add(f"{modname}.{name}")
            except: pass
        return funcs

    def _reset_after_flush(self):
        """Reset counts and start time so next flush is for a new interval (not cumulative)."""
        with self._lock:
            self.call_counts.clear()
            self.call_durations.clear()
            self.error_counts.clear()
            self._call_starts.clear()
            default_recorder.clear()
            self.start_time = time.time()

    def flush(self, report=True):
        with self._lock:
            duration = time.time() - self.start_time
            counts_snapshot = dict(self.call_counts)
            durations_snapshot = dict(self.call_durations)
            errors_snapshot = dict(self.error_counts)

        used = set(counts_snapshot.keys())
        all_funcs = self._get_defined_functions()
        unused = sorted(all_funcs - used)

        out = {
            "duration_sec": round(duration, DURATION_SEC_DECIMALS),
            "called_functions": {},
            "dead_functions": unused,
            "defined_functions": sorted(list(all_funcs)),
            "error_counts": errors_snapshot,
            "feature_flags": default_recorder.snapshot(),
        }
        for key, cnt in counts_snapshot.items():
            tot = durations_snapshot.get(key, 0.0)
            avg_ms = (tot / cnt * MS_PER_SEC) if cnt else 0.0
            out["called_functions"][key] = {
                "count": cnt,
                "total_time_sec": round(tot, TOTAL_TIME_SEC_DECIMALS),
                "avg_time_ms": round(avg_ms, AVG_TIME_MS_DECIMALS)
            }
        ok = flush_data(out, report=report)
        if ok:
            self._reset_after_flush()

    def start(self, include=None, exclude=None, sample_rate=DEFAULT_SAMPLE_RATE):
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

        self._apply_profiler()
        atexit.register(self._shutdown)
        self._start_flush_loop()
        self._initialized = True


# Singleton + API exports
default_profiler = ModulensProfiler()
start = default_profiler.start
stop = default_profiler.stop
flush = default_profiler.flush
