from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch


sys.modules.setdefault(
    "prometheus_client",
    types.SimpleNamespace(
        CollectorRegistry=object,
        Counter=object,
        Gauge=object,
        make_wsgi_app=lambda _registry: object(),
    ),
)

main_module = importlib.import_module("mq_exporter.main")


class _FakeParser:
    def parse_args(self):
        return types.SimpleNamespace(config="exporter.yaml")


class _FakeEvent:
    def __init__(self) -> None:
        self.set_called = False

    def set(self) -> None:
        self.set_called = True

    def wait(self, timeout=None) -> bool:
        raise KeyboardInterrupt()


class _FakeStore:
    registry = object()


class _FakeLifecycle:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class MainTests(unittest.TestCase):
    def test_startup_target_lines_include_pcf_and_admin_objects(self) -> None:
        qmgr = types.SimpleNamespace(
            name="QM1",
            connection=types.SimpleNamespace(
                queue_manager="QM1",
                channel="DEV.APP.SVRCONN",
                conn_name="localhost(1415)",
                user="app",
            ),
            metrics=types.SimpleNamespace(
                include_queue_manager=True,
                include_queues=True,
                include_topics=True,
                include_channels=True,
                include_accounting=True,
                include_statistics=True,
                include_activity_trace=True,
                include_system_topic_stream=True,
                accounting_queue_name="SYSTEM.ADMIN.ACCOUNTING.QUEUE",
                statistics_queue_name="SYSTEM.ADMIN.STATISTICS.QUEUE",
                activity_trace_queue_name="SYSTEM.ADMIN.TRACE.ACTIVITY.QUEUE",
                system_topic_root_topic="SYSTEM.ADMIN.TOPIC",
                queue_patterns=("APP.*",),
                topic_patterns=("SYSTEM.ADMIN.TOPIC",),
                system_topic_subscription_patterns=(
                    "$SYS/MQ/INFO/QMGR/{qmgr}/Monitor/STATMQI/#",
                    "$SYS/MQ/INFO/QMGR/{qmgr}/Monitor/STATQ/#",
                    "$SYS/MQ/INFO/QMGR/{qmgr}/Monitor/STATAPP/#",
                    "$SYS/MQ/INFO/QMGR/{qmgr}/Monitor/CPU/#",
                    "$SYS/MQ/INFO/QMGR/{qmgr}/Monitor/DISK/#",
                ),
                system_topic_diagnostics=True,
                system_topic_startup_probe_window_seconds=9.0,
                system_topic_startup_probe_interval_seconds=3.0,
                channel_patterns=("DEV.*",),
            ),
        )
        config = types.SimpleNamespace(queue_managers=(qmgr,))

        lines = main_module._startup_target_lines(config)

        self.assertTrue(any("PCF command queue: SYSTEM.ADMIN.COMMAND.QUEUE" in line for line in lines))
        self.assertTrue(any("SYSTEM.ADMIN.STATISTICS.QUEUE" in line for line in lines))
        self.assertTrue(any("SYSTEM.ADMIN.TOPIC" in line for line in lines))
        self.assertTrue(any("$SYS/MQ/INFO/QMGR/{qmgr}/Monitor/STATQ/#" in line for line in lines))
        self.assertTrue(any("system topic diagnostics: enabled" in line for line in lines))
        self.assertTrue(any("system topic startup probe window: 9.0s interval=3.0s" in line for line in lines))
        self.assertTrue(any("SYSTEM.ADMIN.TRACE.ACTIVITY.QUEUE" in line for line in lines))
        self.assertTrue(any("Collector mode: pyMQI PCF polling plus admin queue draining." in line for line in lines))

    def test_keyboard_interrupt_stops_services_and_returns_130(self) -> None:
        config = types.SimpleNamespace(
            logging=types.SimpleNamespace(level="INFO"),
            server=object(),
        )
        fake_event = _FakeEvent()
        scheduler = _FakeLifecycle()
        http_server = _FakeLifecycle()

        with (
            patch.object(main_module, "build_parser", return_value=_FakeParser()),
            patch.object(main_module, "load_exporter_config", return_value=config),
            patch.object(main_module, "PyMQICollector", return_value=object()),
            patch.object(main_module, "MetricStore", return_value=_FakeStore()),
            patch.object(main_module.RuntimeState, "from_config", return_value=object()),
            patch.object(main_module, "PollScheduler", return_value=scheduler),
            patch.object(main_module, "MetricsHttpServer", return_value=http_server),
            patch.object(main_module.threading, "Event", return_value=fake_event),
            patch.object(main_module.signal, "signal"),
        ):
            result = main_module.main()

        self.assertEqual(result, 130)
        self.assertTrue(fake_event.set_called)
        self.assertTrue(scheduler.started)
        self.assertTrue(scheduler.stopped)
        self.assertTrue(http_server.started)
        self.assertTrue(http_server.stopped)


if __name__ == "__main__":
    unittest.main()
