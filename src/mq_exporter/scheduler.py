from __future__ import annotations

from dataclasses import dataclass
import logging
from queue import Empty, Queue
from threading import Event, Lock, Thread
import time
from typing import TYPE_CHECKING

from .config import ExporterConfig, QueueManagerConfig

if TYPE_CHECKING:
    from .metrics import MetricStore


LOG = logging.getLogger(__name__)


@dataclass
class _JobState:
    config: QueueManagerConfig
    next_run: float
    running: bool = False


class PollScheduler:
    _WORKER_JOIN_TIMEOUT_SECONDS = 1.0

    def __init__(self, config: ExporterConfig, collector, store: "MetricStore", runtime_state) -> None:
        self._config = config
        self._collector = collector
        self._store = store
        self._runtime_state = runtime_state
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._workers: list[Thread] = []
        self._work_queue: Queue[_JobState | None] = Queue()
        now = time.time()
        self._jobs = {
            qmgr.name: _JobState(config=qmgr, next_run=now)
            for qmgr in config.queue_managers
            if qmgr.enabled
        }

    def start(self) -> None:
        if self._thread is not None:
            return
        self._start_workers()
        self._thread = Thread(target=self._run_loop, name="poll-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        for _ in self._workers:
            self._work_queue.put(None)
        for worker in self._workers:
            worker.join(timeout=self._WORKER_JOIN_TIMEOUT_SECONDS)
            if worker.is_alive():
                LOG.warning("Worker thread %s did not exit before shutdown timeout", worker.name)

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
        self._work_queue.put(job)

    def _poll_once(self, config: QueueManagerConfig):
        start = time.time()
        records = self._collector.collect(config)
        return records, time.time() - start

    def _start_workers(self) -> None:
        for index in range(self._config.worker_pool.max_threads):
            worker = Thread(target=self._worker_loop, name=f"mq-poll-{index + 1}", daemon=True)
            worker.start()
            self._workers.append(worker)

    def _worker_loop(self) -> None:
        while True:
            try:
                job = self._work_queue.get(timeout=0.5)
            except Empty:
                if self._stop.is_set():
                    return
                continue

            if job is None:
                self._work_queue.task_done()
                return

            self._complete(job)
            self._work_queue.task_done()

    def _complete(self, job: _JobState) -> None:
        name = job.config.name
        try:
            records, duration = self._poll_once(job.config)
        except Exception as exc:
            error_message = str(exc)
            LOG.error("Background poll failed for %s: %s", name, error_message, exc_info=True)
            self._store.record_failure(name, 0.0)
            self._runtime_state.mark_failure(name, error_message)
        else:
            self._store.record_success(name, duration, records)
            self._runtime_state.mark_success(name, duration, len(records))
            LOG.debug("Completed poll for %s with %d metrics", name, len(records))
        finally:
            with self._lock:
                job.running = False
                job.next_run = time.time() + job.config.poll_interval_seconds
