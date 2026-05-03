from __future__ import annotations

import sys
import types
import unittest

sys.modules.setdefault(
    "prometheus_client",
    types.SimpleNamespace(CollectorRegistry=object, Counter=object, Gauge=object, make_wsgi_app=lambda _registry: object()),
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
    def _collector_with_admin_pcf(self, unpacked):
        collector = PyMQICollector.__new__(PyMQICollector)
        collector.pymqi = types.SimpleNamespace(
            MQMIError=_FakeMQMIError,
            CMQC=types.SimpleNamespace(
                MQOT_Q=1,
                MQRC_UNKNOWN_OBJECT_NAME=2085,
            ),
            CMQCFC=types.SimpleNamespace(
                MQGACF_Q_ACCOUNTING_DATA=8010,
                MQGACF_ACTIVITY=8005,
                MQCACF_APPL_NAME=3024,
                MQCACF_OBJECT_NAME=3046,
                MQIACF_OBJECT_TYPE=1016,
                MQIAMO_PUTS=735,
                MQIAMO_GETS=722,
                MQIAMO64_PUT_BYTES=748,
                MQIACF_OPERATION_TYPE=1240,
                MQIACF_OPERATION_ID=1356,
                MQOPER_GET=3,
            ),
            PCFExecute=types.SimpleNamespace(unpack=lambda _payload: (unpacked, object())),
        )
        return collector

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

    def test_accounting_message_generates_app_object_metrics(self) -> None:
        collector = self._collector_with_admin_pcf(
            {
                8010: [
                    {
                        3024: b"amqsputc",
                        3046: b"APP.REQUEST",
                        1016: 1,
                        735: 5,
                        722: 2,
                        748: 120,
                    }
                ]
            }
        )
        config = QueueManagerConfig(
            name="QM1",
            enabled=True,
            poll_interval_seconds=30.0,
            timeout_seconds=10.0,
            connection=ConnectionConfig(queue_manager="QM1", channel="DEV.APP.SVRCONN", conn_name="localhost(1414)"),
        )

        records = collector._parse_accounting_message(config, "SYSTEM.ADMIN.ACCOUNTING.QUEUE", types.SimpleNamespace(PutApplName=b""), b"pcf")

        by_name = {record.name: record for record in records}
        self.assertEqual(by_name["ibmmq_accounting_puts"].labels["appl_name"], "amqsputc")
        self.assertEqual(by_name["ibmmq_accounting_puts"].labels["object_name"], "APP.REQUEST")
        self.assertEqual(by_name["ibmmq_accounting_puts"].labels["object_type"], "MQOT_Q")
        self.assertEqual(by_name["ibmmq_accounting_puts"].value, 5.0)
        self.assertEqual(by_name["ibmmq_accounting_gets"].value, 2.0)
        self.assertEqual(by_name["ibmmq_accounting_put_bytes"].value, 120.0)

    def test_activity_trace_message_generates_operation_metric(self) -> None:
        collector = self._collector_with_admin_pcf(
            {
                8005: [
                    {
                        3024: b"amqsgetc",
                        3046: b"APP.REQUEST",
                        1016: 1,
                        1240: 3,
                        1356: 44,
                    }
                ]
            }
        )
        config = QueueManagerConfig(
            name="QM1",
            enabled=True,
            poll_interval_seconds=30.0,
            timeout_seconds=10.0,
            connection=ConnectionConfig(queue_manager="QM1", channel="DEV.APP.SVRCONN", conn_name="localhost(1414)"),
        )

        records = collector._parse_activity_trace_message(config, "SYSTEM.ADMIN.TRACE.ACTIVITY.QUEUE", types.SimpleNamespace(PutApplName=b""), b"pcf")

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.name, "ibmmq_activity_operations")
        self.assertEqual(record.labels["appl_name"], "amqsgetc")
        self.assertEqual(record.labels["object_name"], "APP.REQUEST")
        self.assertEqual(record.labels["operation"], "MQOPER_GET")
        self.assertEqual(record.labels["operation_id"], "44")
        self.assertEqual(record.value, 1.0)


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
