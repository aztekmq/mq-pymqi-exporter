from __future__ import annotations

import argparse
import logging
from pathlib import Path
import signal
import threading

from .config import load_exporter_config
from .http_server import MetricsHttpServer
from .metrics import MetricStore
from .mq import PyMQICollector
from .runtime_state import RuntimeState
from .scheduler import PollScheduler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IBM MQ Prometheus exporter using background pyMQI polling.")
    parser.add_argument("--config", required=True, help="Path to exporter YAML file.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_path = str(Path(args.config).resolve())
    config = load_exporter_config(config_path)
    logging.basicConfig(
        level=getattr(logging, config.logging.level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    stop_event = threading.Event()
    collector = PyMQICollector()
    store = MetricStore()
    runtime_state = RuntimeState.from_config(config, config_path)
    scheduler = PollScheduler(config, collector, store, runtime_state)
    http_server = MetricsHttpServer(config.server, store.registry, runtime_state)

    def _stop(_signum=None, _frame=None) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    http_server.start()
    scheduler.start()
    stop_event.wait()
    scheduler.stop()
    http_server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
