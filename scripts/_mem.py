"""Peak-memory measurement helper used by the benchmark scripts.

On Windows psutil exposes the OS-tracked peak working set (``peak_wset``),
which is exact. Elsewhere a background thread samples RSS every 50 ms.
"""
from __future__ import annotations

import threading
import time

import psutil


class PeakMemory:
    def __init__(self, interval: float = 0.05):
        self.proc = psutil.Process()
        self.interval = interval
        self._peak = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        while not self._stop.is_set():
            self._peak = max(self._peak, self.proc.memory_info().rss)
            time.sleep(self.interval)

    def __enter__(self) -> "PeakMemory":
        self._start_rss = self.proc.memory_info().rss
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        info = self.proc.memory_info()
        os_peak = getattr(info, "peak_wset", 0)
        self._peak = max(self._peak, os_peak, info.rss)

    @property
    def peak_mb(self) -> float:
        return round(self._peak / (1024 * 1024), 1)
