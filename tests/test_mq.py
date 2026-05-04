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


class _FakeRFH2:
    def __init__(self) -> None:
        self._values = {}

    def unpack(self, _payload, _encoding=None) -> None:
        self._values = {
            "StrucLength": 8,
            "mqps": b"<mqps><Top>$SYS/MQ/INFO/QMGR/QM1/Monitor/STATQ/Queue/APP.REQUEST</Top></mqps>",
        }

    def __getitem__(self, key):
        return self._values[key]

    def get(self):
        return self._values


class _FakeDiscoveryRFH2(_FakeRFH2):
    def unpack(self, _payload, _encoding=None) -> None:
        self._values = {
            "StrucLength": 8,
            "mqps": b"<mqps><Top>$SYS/MQ/INFO/QMGR/QM1/Monitor/META</Top></mqps>",
        }


class _FakeStatmqiRFH2(_FakeRFH2):
    def unpack(self, _payload, _encoding=None) -> None:
        self._values = {
            "StrucLength": 8,
            "mqps": b"<mqps><Top>$SYS/MQ/INFO/QMGR/QM1/Monitor/STATMQI/PUT</Top></mqps>",
        }


class _FakeCpuRFH2(_FakeRFH2):
    def unpack(self, _payload, _encoding=None) -> None:
        self._values = {
            "StrucLength": 8,
            "mqps": b"<mqps><Top>$SYS/MQ/INFO/QMGR/QM1/Monitor/CPU/SystemSummary</Top></mqps>",
        }


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
                MQOT_TOPIC=8,
                MQFMT_RF_HEADER_2=b"MQHRF2  ",
                MQRFH_STRUC_ID=b"RFH ",
                MQRC_UNKNOWN_OBJECT_NAME=2085,
            ),
            CMQCFC=types.SimpleNamespace(
                MQGACF_Q_ACCOUNTING_DATA=8010,
                MQGACF_Q_STATISTICS_DATA=8011,
                MQGACF_ACTIVITY=8005,
                MQCACF_APPL_NAME=3024,
                MQCAMO_MONITOR_DESC=3065,
                MQCAMO_MONITOR_TYPE=3066,
                MQCACF_OBJECT_NAME=3046,
                MQCACF_Q_NAME=2016,
                MQIACF_OBJECT_TYPE=1016,
                MQIAMO_OPENS=733,
                MQIAMO_CLOSES=709,
                MQIAMO_INQS=727,
                MQIAMO_SETS=744,
                MQIAMO_PUTS=735,
                MQIAMO_GETS=722,
                MQIAMO_PUTS_FAILED=736,
                MQIAMO_GETS_FAILED=723,
                MQIAMO_BROWSES=720,
                MQIAMO_CONNS=712,
                MQIAMO_CONNS_FAILED=749,
                MQIAMO_CBS=769,
                MQIAMO_COMMITS=710,
                MQIAMO_TOPIC_PUTS=779,
                MQIAMO_Q_MAX_DEPTH=739,
                MQIAMO_Q_MIN_DEPTH=740,
                MQIAMO64_PUT_BYTES=748,
                MQIAMO64_GET_BYTES=747,
                MQIAMO64_BYTES=746,
                MQIAMO64_Q_TIME_AVG=741,
                MQIAMO64_TOPIC_PUT_BYTES=783,
                MQIAMO64_MONITOR_INTERVAL=3902,
                MQIA_MAX_Q_DEPTH=15,
                MQIA_Q_DEPTH_HIGH_LIMIT=40,
                MQIACF_OPERATION_TYPE=1240,
                MQIACF_OPERATION_ID=1356,
                MQOPER_GET=3,
            ),
            RFH2=_FakeRFH2,
            PCFExecute=types.SimpleNamespace(unpack=lambda _payload: (unpacked, object())),
        )
        collector._selector_names = collector._build_selector_name_map()
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

    def test_statistics_message_sums_list_values_and_keeps_clean_labels(self) -> None:
        collector = self._collector_with_admin_pcf(
            {
                8011: [
                    {
                        2016: b"APP.REQUEST",
                        1016: 1,
                        735: [2, 3],
                        722: [1, 4],
                        720: [0, 2],
                        748: [100, 25],
                        747: [40, 5],
                        736: 1,
                        723: 2,
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

        records = collector._parse_statistics_message(config, "SYSTEM.ADMIN.STATISTICS.QUEUE", types.SimpleNamespace(PutApplName=b""), b"pcf")

        by_name = {record.name: record for record in records}
        self.assertEqual(by_name["ibmmq_statistics_puts"].labels["object_name"], "APP.REQUEST")
        self.assertEqual(by_name["ibmmq_statistics_puts"].value, 5.0)
        self.assertEqual(by_name["ibmmq_statistics_gets"].value, 5.0)
        self.assertEqual(by_name["ibmmq_statistics_browses"].value, 2.0)
        self.assertEqual(by_name["ibmmq_statistics_put_bytes"].value, 125.0)
        self.assertEqual(by_name["ibmmq_statistics_get_bytes"].value, 45.0)
        self.assertEqual(by_name["ibmmq_statistics_puts_failed"].value, 1.0)
        self.assertEqual(by_name["ibmmq_statistics_gets_failed"].value, 2.0)

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

    def test_normalize_mq_string_decodes_byte_values(self) -> None:
        self.assertEqual(PyMQICollector._normalize_mq_string(b"APP.REQUEST                                     "), "APP.REQUEST")

    def test_system_topic_publication_generates_topic_and_pcf_metrics(self) -> None:
        collector = self._collector_with_admin_pcf(
            {
                733: 3,
                735: 5,
                739: 12,
                741: 5000000,
                3902: 10000000,
                15: 5000,
                40: 4000,
                3046: b"APP.REQUEST",
                1016: 1,
            }
        )
        config = QueueManagerConfig(
            name="QM1",
            enabled=True,
            poll_interval_seconds=30.0,
            timeout_seconds=10.0,
            connection=ConnectionConfig(queue_manager="QM1", channel="DEV.APP.SVRCONN", conn_name="localhost(1414)"),
        )

        records = collector._parse_system_topic_publication(
            config,
            types.SimpleNamespace(Format=b"MQHRF2  ", Encoding=273),
            b"RFH bodypcf",
        )

        by_name = {}
        for record in records:
            by_name.setdefault(record.name, []).append(record)

        publication = by_name["ibmmq_system_topic_publications"][0]
        self.assertEqual(publication.labels["published_topic"], "$SYS/MQ/INFO/QMGR/QM1/Monitor/STATQ/Queue/APP.REQUEST")
        self.assertEqual(publication.labels["monitor_class"], "STATQ")
        self.assertEqual(publication.labels["monitor_branch"], "Queue")
        self.assertEqual(publication.labels["monitor_leaf"], "APP.REQUEST")

        pcf_metric = by_name["ibmmq_system_topic_mqiamo_puts"][0]
        self.assertEqual(pcf_metric.labels["object_name"], "APP.REQUEST")
        self.assertEqual(pcf_metric.labels["object_type"], "MQOT_Q")
        self.assertEqual(pcf_metric.value, 5.0)

        normalized_metric = by_name["ibmmq_statq_puts"][0]
        self.assertEqual(normalized_metric.labels["monitor_branch"], "Queue")
        self.assertEqual(normalized_metric.labels["monitor_leaf"], "APP.REQUEST")
        self.assertEqual(normalized_metric.value, 5.0)

        explicit_metric = by_name["ibmmq_statq_messages_put_total"][0]
        self.assertEqual(explicit_metric.value, 5.0)

        open_metric = by_name["ibmmq_statq_mqopen_total"][0]
        self.assertEqual(open_metric.value, 3.0)

        queue_time_metric = by_name["ibmmq_statq_queue_time_average_seconds"][0]
        self.assertEqual(queue_time_metric.value, 5.0)

        depth_high_metric = by_name["ibmmq_statq_queue_depth_high_watermark"][0]
        self.assertEqual(depth_high_metric.value, 12.0)

        depth_limit_metric = by_name["ibmmq_statq_queue_depth_high_limit"][0]
        self.assertEqual(depth_limit_metric.value, 4000.0)

        max_depth_metric = by_name["ibmmq_statq_queue_depth_max_configured"][0]
        self.assertEqual(max_depth_metric.value, 5000.0)

        interval_metric = by_name["ibmmq_statq_monitor_interval_seconds"][0]
        self.assertEqual(interval_metric.value, 10.0)

    def test_system_topic_publication_generates_discovery_metric_for_unclassified_branch(self) -> None:
        collector = self._collector_with_admin_pcf({735: 5})
        collector.pymqi.RFH2 = _FakeDiscoveryRFH2
        config = QueueManagerConfig(
            name="QM1",
            enabled=True,
            poll_interval_seconds=30.0,
            timeout_seconds=10.0,
            connection=ConnectionConfig(queue_manager="QM1", channel="DEV.APP.SVRCONN", conn_name="localhost(1414)"),
        )

        records = collector._parse_system_topic_publication(
            config,
            types.SimpleNamespace(Format=b"MQHRF2  ", Encoding=273),
            b"RFH bodypcf",
        )

        discovery = [record for record in records if record.name == "ibmmq_monitor_discovery_publications"]
        self.assertEqual(len(discovery), 1)
        self.assertEqual(discovery[0].labels["monitor_class"], "META")

    def test_system_topic_publication_generates_curated_statmqi_metrics(self) -> None:
        collector = self._collector_with_admin_pcf(
            {
                712: 2,
                749: 1,
                769: 4,
                710: 6,
                779: 8,
                783: 2048,
            }
        )
        collector.pymqi.RFH2 = _FakeStatmqiRFH2
        config = QueueManagerConfig(
            name="QM1",
            enabled=True,
            poll_interval_seconds=30.0,
            timeout_seconds=10.0,
            connection=ConnectionConfig(queue_manager="QM1", channel="DEV.APP.SVRCONN", conn_name="localhost(1414)"),
        )

        records = collector._parse_system_topic_publication(
            config,
            types.SimpleNamespace(Format=b"MQHRF2  ", Encoding=273),
            b"RFH bodypcf",
        )

        by_name = {}
        for record in records:
            by_name.setdefault(record.name, []).append(record)

        self.assertEqual(by_name["ibmmq_statmqi_mqconn_mqconnx_total"][0].value, 2.0)
        self.assertEqual(by_name["ibmmq_statmqi_mqconn_mqconnx_failures_total"][0].value, 1.0)
        self.assertEqual(by_name["ibmmq_statmqi_mqcb_total"][0].value, 4.0)
        self.assertEqual(by_name["ibmmq_statmqi_commit_total"][0].value, 6.0)
        self.assertEqual(by_name["ibmmq_statmqi_topic_mqput_mqput1_total"][0].value, 8.0)
        self.assertEqual(by_name["ibmmq_statmqi_topic_put_bytes_total"][0].value, 2048.0)

    def test_system_topic_publication_generates_curated_cpu_metrics(self) -> None:
        collector = self._collector_with_admin_pcf(
            {
                746: 2048,
                3065: b"RAM total bytes",
                3066: b"SystemSummary",
            }
        )
        collector.pymqi.RFH2 = _FakeCpuRFH2
        config = QueueManagerConfig(
            name="QM1",
            enabled=True,
            poll_interval_seconds=30.0,
            timeout_seconds=10.0,
            connection=ConnectionConfig(queue_manager="QM1", channel="DEV.APP.SVRCONN", conn_name="localhost(1414)"),
        )

        records = collector._parse_system_topic_publication(
            config,
            types.SimpleNamespace(Format=b"MQHRF2  ", Encoding=273),
            b"RFH bodypcf",
        )

        cpu_metric = [record for record in records if record.name == "ibmmq_cpu_bytes_current"][0]
        self.assertEqual(cpu_metric.value, 2048.0)
        self.assertEqual(cpu_metric.labels["monitor_desc"], "RAM total bytes")
        self.assertEqual(cpu_metric.labels["monitor_type_desc"], "SystemSummary")


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
