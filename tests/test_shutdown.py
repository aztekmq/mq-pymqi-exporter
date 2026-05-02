from __future__ import annotations

import threading
import time
import unittest

from mq_exporter.config import (
    ConnectionConfig,
    ExporterConfig,
    LoggingConfig,
    MetricsConfig,
    QueueManagerConfig,
    ServerConfig,
    WorkerPoolConfig,
)
from mq_exporter.runtime_state import RuntimeState
from mq_exporter.scheduler import PollScheduler


class _BlockingCollector:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def collect(self, _config) -> list:
        self.started.set()
        self.release.wait(timeout=5)
        return []


class _StoreStub:
    def set_next_poll(self, _qmgr: str, _when: float) -> None:
        return None

    def record_success(self, _qmgr: str, _duration_seconds: float, _records) -> None:
        return None

    def record_failure(self, _qmgr: str, _duration_seconds: float) -> None:
        return None


class ShutdownTests(unittest.TestCase):
    def test_scheduler_stop_does_not_block_on_stuck_poll(self) -> None:
        qmgr = QueueManagerConfig(
            name="QM1",
            enabled=True,
            poll_interval_seconds=0.1,
            timeout_seconds=30.0,
            connection=ConnectionConfig(
                queue_manager="QM1",
                channel="DEV.APP.SVRCONN",
                conn_name="localhost(1415)",
            ),
            metrics=MetricsConfig(),
        )
        config = ExporterConfig(
            server=ServerConfig(),
            worker_pool=WorkerPoolConfig(max_threads=1, scheduler_tick_seconds=0.01),
            logging=LoggingConfig(),
            queue_managers=(qmgr,),
        )
        collector = _BlockingCollector()
        scheduler = PollScheduler(
            config,
            collector,
            _StoreStub(),
            RuntimeState.from_config(config, "tests/shutdown.yaml"),
        )

        scheduler.start()
        self.assertTrue(collector.started.wait(timeout=1), "poll worker did not start")

        started = time.monotonic()
        scheduler.stop()
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 2.0, "scheduler.stop() blocked on an in-flight poll")
        collector.release.set()


if __name__ == "__main__":
    unittest.main()
