from __future__ import annotations

import sys
import types
import unittest

sys.modules.setdefault(
    "prometheus_client",
    types.SimpleNamespace(CollectorRegistry=object, Counter=object, Gauge=object),
)

from mq_exporter.config import (
    ConnectionConfig,
    ExporterConfig,
    LoggingConfig,
    MetricsConfig,
    QueueManagerConfig,
    ServerConfig,
    WorkerPoolConfig,
)
from mq_exporter.mq import MQCollectionError, PyMQICollector
from mq_exporter.runtime_state import RuntimeState
from mq_exporter.scheduler import PollScheduler


class _FakeMQMIError(Exception):
    def __init__(self, comp: int, reason: int) -> None:
        super().__init__(f"Comp: {comp}, Reason {reason}")
        self.comp = comp
        self.reason = reason


class _FakePCF:
    def MQCMD_INQUIRE_Q(self, _args):
        raise _FakeMQMIError(2, 2085)


class _FakeStore:
    def set_next_poll(self, _qmgr: str, _when: float) -> None:
        return None

    def record_success(self, _qmgr: str, _duration_seconds: float, _records) -> None:
        return None

    def record_failure(self, _qmgr: str, _duration_seconds: float) -> None:
        return None


class _RaisingCollector:
    def collect(self, _config):
        raise RuntimeError("structured poll failure")


class MQCollectorTests(unittest.TestCase):
    def test_unknown_queue_name_is_included_in_error_message(self) -> None:
        collector = PyMQICollector.__new__(PyMQICollector)
        collector.pymqi = types.SimpleNamespace(
            MQMIError=_FakeMQMIError,
            CMQC=types.SimpleNamespace(
                MQCA_Q_NAME=1,
                MQIA_Q_TYPE=2,
                MQQT_LOCAL=3,
                MQRC_UNKNOWN_OBJECT_NAME=2085,
            ),
            CMQCFC=types.SimpleNamespace(),
        )
        config = QueueManagerConfig(
            name="QM1",
            enabled=True,
            poll_interval_seconds=30.0,
            timeout_seconds=10.0,
            connection=ConnectionConfig(
                queue_manager="QM1",
                channel="DEV.APP.SVRCONN",
                conn_name="localhost(1414)",
            ),
            metrics=MetricsConfig(queue_patterns=("APP.INPUT.QUEUE",)),
        )

        with self.assertRaises(MQCollectionError) as context:
            collector._collect_queue_metrics(config, _FakePCF())

        message = str(context.exception)
        self.assertIn("MQCMD_INQUIRE_Q", message)
        self.assertIn("queue='APP.INPUT.QUEUE'", message)
        self.assertIn("reason=2085 (MQRC_UNKNOWN_OBJECT_NAME)", message)
        self.assertIn("The requested queue name 'APP.INPUT.QUEUE' is unknown", message)


class SchedulerFailureTests(unittest.TestCase):
    def test_scheduler_records_exception_message_in_runtime_state(self) -> None:
        qmgr = QueueManagerConfig(
            name="QM1",
            enabled=True,
            poll_interval_seconds=30.0,
            timeout_seconds=10.0,
            connection=ConnectionConfig(
                queue_manager="QM1",
                channel="DEV.APP.SVRCONN",
                conn_name="localhost(1414)",
            ),
        )
        config = ExporterConfig(
            server=ServerConfig(),
            worker_pool=WorkerPoolConfig(max_threads=1, scheduler_tick_seconds=0.01),
            logging=LoggingConfig(),
            queue_managers=(qmgr,),
        )
        runtime_state = RuntimeState.from_config(config, "tests/runtime.yaml")
        scheduler = PollScheduler(config, _RaisingCollector(), _FakeStore(), runtime_state)
        job = scheduler._jobs["QM1"]

        scheduler._complete(job)

        self.assertEqual(runtime_state.queue_managers["QM1"].last_error, "structured poll failure")


if __name__ == "__main__":
    unittest.main()
