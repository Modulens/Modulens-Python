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
from .flush import flush_data

STDLIB_PATH = sysconfig.get_paths().get("stdlib", "")
SITE_PACKAGES = set(site.getsitepackages())
VENV_PREFIXES = [p for p in sys.path if "site-packages" in p or "venv" in p or "env" in p]

class ModulensProfiler:
    def __init__(self):
        self.call_counts = defaultdict(int)
        self.call_durations = defaultdict(float)
        self.start_time = time.time()
        self.included = set()
        self.excluded = set(config.get("exclude", []))
        self.observed_modules = set()
        self.sample_rate = 1.0
        self.flush_interval = config.get("flush_interval", 60)
        self._flush_thread = None
        self._stop_event = threading.Event()
        self._initialized = False

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
        fn = frame.f_code.co_filename
        if not mod or not fn:
            return False

        # Filter by include/exclude
        if self.included:
            if not any(mod.startswith(p) for p in self.included):
                return False
        if any(mod.startswith(p) for p in self.excluded):
            return False

        # Filter by path
        if self._is_third_party_or_stdlib(fn):
            return False

        self.observed_modules.add(mod)
        return True

    def _func_key(self, frame):
        return f"{frame.f_globals.get('__name__', '__main__')}.{frame.f_code.co_name}"

    def _profile_handler(self, frame, event, arg):
        if event == "call":
            if not self._should_track(frame):
                return
            if random.random() > self.sample_rate:
                return
            key = self._func_key(frame)
            self.call_counts[key] += 1
            frame.f_locals["_modulens_start"] = time.perf_counter()

        elif event == "return":
            if not self._should_track(frame):
                return
            start = frame.f_locals.get("_modulens_start")
            if start:
                key = self._func_key(frame)
                elapsed = time.perf_counter() - start
                self.call_durations[key] += elapsed

    def _apply_profiler(self):
        sys.setprofile(self._profile_handler)
        threading.setprofile(self._profile_handler)

    def _start_flush_loop(self):
        def loop():
            while not self._stop_event.wait(self.flush_interval):
                try:
                    self.flush(report=False)
                except Exception as e:
                    print(f"[Modulens] Auto-flush error: {e}")
        self._flush_thread = threading.Thread(target=loop, daemon=True)
        self._flush_thread.start()

    def _shutdown(self):
        self._stop_event.set()
        if self._flush_thread:
            self._flush_thread.join(timeout=2)
        self.flush(report=True)

    def _get_defined_functions(self):
        funcs = set()
        for modname in self.observed_modules:
            try:
                mod = sys.modules.get(modname)
                for name, obj in inspect.getmembers(mod, inspect.isfunction):
                    fn = getattr(obj, "__code__", None).co_filename
                    if not fn or fn.startswith(STDLIB_PATH) or any(fn.startswith(p) for p in SITE_PACKAGES) or any(fn.startswith(p) for p in VENV_PREFIXES):
                        continue
                    funcs.add(f"{modname}.{name}")
            except: pass
        return funcs

    def flush(self, report=True):
        duration = time.time() - self.start_time
        used = set(self.call_counts.keys())
        all_funcs = self._get_defined_functions()
        unused = sorted(all_funcs - used)

        out = {
            "duration_sec": round(duration, 2),
            "called_functions": {},
            "dead_functions": unused,
            "defined_functions": sorted(list(all_funcs))
        }
        for key, cnt in self.call_counts.items():
            tot = self.call_durations.get(key, 0.0)
            avg_ms = (tot / cnt * 1000.0) if cnt else 0.0
            out["called_functions"][key] = {
                "count": cnt,
                "total_time_sec": round(tot, 4),
                "avg_time_ms": round(avg_ms, 2)
            }
        flush_data(out, report=report)

    def start(self, include=None, exclude=None, sample_rate=1.0):
        if self._initialized:
            print("[Modulens] ⚠️ Profiler already started")
            return

        if include is None:
            print(
                "[Modulens] ⚠️ WARNING: No 'include' filter provided.\n"
                "         You may accidentally track stdlib or third-party packages.\n"
                "         Pass include=['your_project'] to avoid noisy data.\n"
            )

        self.sample_rate = sample_rate
        if include:
            self.included = set(include)
        if exclude:
            self.excluded.update(exclude)

        self._apply_profiler()
        atexit.register(self._shutdown)
        self._start_flush_loop()
        self._initialized = True


# Singleton + API exports
default_profiler = ModulensProfiler()
start = default_profiler.start
stop = default_profiler.flush
flush = default_profiler.flush
