from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import RLock
import time
from typing import Any

from .config import ExporterConfig, QueueManagerConfig


@dataclass
class QueueManagerRuntime:
    enabled: bool
    poll_interval_seconds: float
    timeout_seconds: float
    running: bool = False
    last_attempt_unixtime: float | None = None
    last_success_unixtime: float | None = None
    last_completion_unixtime: float | None = None
    next_poll_unixtime: float | None = None
    last_duration_seconds: float | None = None
    last_error: str | None = None
    last_metric_count: int = 0
    success_count: int = 0
    failure_count: int = 0


@dataclass
class RuntimeState:
    started_unixtime: float
    config_path: str
    server: dict[str, Any]
    worker_pool: dict[str, Any]
    logging: dict[str, Any]
    queue_managers: dict[str, QueueManagerRuntime] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._lock = RLock()

    @classmethod
    def from_config(cls, config: ExporterConfig, config_path: str) -> "RuntimeState":
        state = cls(
            started_unixtime=time.time(),
            config_path=config_path,
            server=asdict(config.server),
            worker_pool=asdict(config.worker_pool),
            logging=asdict(config.logging),
        )
        for qmgr in config.queue_managers:
            state.queue_managers[qmgr.name] = QueueManagerRuntime(
                enabled=qmgr.enabled,
                poll_interval_seconds=qmgr.poll_interval_seconds,
                timeout_seconds=qmgr.timeout_seconds,
            )
        return state

    def mark_scheduled(self, qmgr: QueueManagerConfig, next_poll_unixtime: float) -> None:
        with self._lock:
            self.queue_managers[qmgr.name].next_poll_unixtime = next_poll_unixtime

    def mark_running(self, qmgr: QueueManagerConfig) -> None:
        with self._lock:
            runtime = self.queue_managers[qmgr.name]
            runtime.running = True
            runtime.last_attempt_unixtime = time.time()

    def mark_success(self, qmgr_name: str, duration_seconds: float, metric_count: int) -> None:
        now = time.time()
        with self._lock:
            runtime = self.queue_managers[qmgr_name]
            runtime.running = False
            runtime.last_success_unixtime = now
            runtime.last_completion_unixtime = now
            runtime.last_duration_seconds = duration_seconds
            runtime.last_metric_count = metric_count
            runtime.last_error = None
            runtime.success_count += 1

    def mark_failure(self, qmgr_name: str, error: str) -> None:
        now = time.time()
        with self._lock:
            runtime = self.queue_managers[qmgr_name]
            runtime.running = False
            runtime.last_completion_unixtime = now
            runtime.last_error = error
            runtime.failure_count += 1

    def snapshot_status(self) -> dict[str, Any]:
        with self._lock:
            qmgrs = {
                name: asdict(runtime)
                for name, runtime in self.queue_managers.items()
            }
        return {
            "started_unixtime": self.started_unixtime,
            "uptime_seconds": max(0.0, time.time() - self.started_unixtime),
            "queue_managers": qmgrs,
        }

    def snapshot_info(self) -> dict[str, Any]:
        with self._lock:
            qmgrs = {
                name: {
                    "enabled": runtime.enabled,
                    "poll_interval_seconds": runtime.poll_interval_seconds,
                    "timeout_seconds": runtime.timeout_seconds,
                }
                for name, runtime in self.queue_managers.items()
            }
        return {
            "config_path": self.config_path,
            "server": self.server,
            "worker_pool": self.worker_pool,
            "logging": self.logging,
            "queue_managers": qmgrs,
        }
