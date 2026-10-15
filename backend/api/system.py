"""Нагрузка на машину (CPU, память, диск, сеть) — без Prometheus, прямо из процесса API.

Сэмплер раз в 5 секунд пишет точку в кольцевой буфер на 24 часа.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import asdict, dataclass

import psutil

INTERVAL_S = 5
KEEP = 24 * 3600 // INTERVAL_S


@dataclass
class Sample:
    ts: float
    cpu: float
    mem: float
    disk: float
    net_in_kbps: float
    net_out_kbps: float
    proc_mem_mb: float


class SystemSampler:
    def __init__(self) -> None:
        self.samples: deque[Sample] = deque(maxlen=KEEP)
        self._task: asyncio.Task | None = None
        self._last_net = psutil.net_io_counters()
        self._last_t = time.monotonic()
        self._proc = psutil.Process()
        psutil.cpu_percent(None)  # первый вызов «прогревает» счётчик

    def sample(self) -> Sample:
        net = psutil.net_io_counters()
        now = time.monotonic()
        dt = max(now - self._last_t, 1e-6)
        s = Sample(
            ts=time.time(),
            cpu=psutil.cpu_percent(None),
            mem=psutil.virtual_memory().percent,
            disk=psutil.disk_usage("/").percent,
            net_in_kbps=round((net.bytes_recv - self._last_net.bytes_recv) * 8 / 1024 / dt, 1),
            net_out_kbps=round((net.bytes_sent - self._last_net.bytes_sent) * 8 / 1024 / dt, 1),
            proc_mem_mb=round(self._proc.memory_info().rss / 1024 / 1024, 1),
        )
        self._last_net, self._last_t = net, now
        self.samples.append(s)
        return s

    async def run(self) -> None:
        while True:
            try:
                self.sample()
            except Exception:  # noqa: BLE001 — метрики не должны ронять API
                pass
            await asyncio.sleep(INTERVAL_S)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def series(self, minutes: int) -> list[dict]:
        since = time.time() - minutes * 60
        points = [s for s in self.samples if s.ts >= since]
        # Не больше ~300 точек на график
        step = max(len(points) // 300, 1)
        return [asdict(p) for p in points[::step]]

    def info(self) -> dict:
        boot = psutil.boot_time()
        vm = psutil.virtual_memory()
        return {
            "cpu_count": psutil.cpu_count(),
            "mem_total_gb": round(vm.total / 1024**3, 1),
            "uptime_h": round((time.time() - boot) / 3600, 1),
        }


sampler = SystemSampler()
