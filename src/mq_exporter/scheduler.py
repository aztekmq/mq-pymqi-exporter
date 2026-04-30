from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import logging
from threading import Event, Lock, Thread
import time

from .config import ExporterConfig, QueueManagerConfig
from .metrics import MetricStore


LOG = logging.getLogger(__name__)


@dataclass
class _JobState:
    config: QueueManagerConfig
    next_run: float
    running: bool = False


class PollScheduler:
    def __init__(self, config: ExporterConfig, collector, store: MetricStore, runtime_state) -> None:
        self._config = config
        self._collector = collector
        self._store = store
        self._runtime_state = runtime_state
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._executor = ThreadPoolExecutor(max_workers=config.worker_pool.max_threads, thread_name_prefix="mq-poll")
        now = time.time()
        self._jobs = {
            qmgr.name: _JobState(config=qmgr, next_run=now)
            for qmgr in config.queue_managers
            if qmgr.enabled
        }

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run_loop, name="poll-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run_loop(self) -> None:
        tick = self._config.worker_pool.scheduler_tick_seconds
        while not self._stop.is_set():
            now = time.time()
            for job in self._jobs.values():
                self._store.set_next_poll(job.config.name, job.next_run)
                self._runtime_state.mark_scheduled(job.config, job.next_run)
                if job.running or now < job.next_run:
                    continue
                self._submit(job)
            self._stop.wait(tick)

    def _submit(self, job: _JobState) -> None:
        with self._lock:
            if job.running:
                return
            job.running = True
        self._runtime_state.mark_running(job.config)
        future = self._executor.submit(self._poll_once, job.config)
        future.add_done_callback(lambda done, name=job.config.name: self._complete(name, done))

    def _poll_once(self, config: QueueManagerConfig):
        start = time.time()
        records = self._collector.collect(config)
        return records, time.time() - start

    def _complete(self, name: str, future: Future) -> None:
        job = self._jobs[name]
        try:
            records, duration = future.result(timeout=job.config.timeout_seconds)
        except Exception:
            LOG.exception("Background poll failed for %s", name)
            duration = 0.0
            self._store.record_failure(name, duration)
            self._runtime_state.mark_failure(name, "background poll failed; see exporter logs")
        else:
            self._store.record_success(name, duration, records)
            self._runtime_state.mark_success(name, duration, len(records))
            LOG.debug("Completed poll for %s with %d metrics", name, len(records))
        finally:
            with self._lock:
                job.running = False
                job.next_run = time.time() + job.config.poll_interval_seconds
