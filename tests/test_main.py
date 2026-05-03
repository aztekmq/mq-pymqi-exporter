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
