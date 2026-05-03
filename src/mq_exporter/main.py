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


LOG = logging.getLogger(__name__)


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
    interrupt_count = 0
    forced_interrupt = False

    def _stop(_signum=None, _frame=None) -> None:
        nonlocal interrupt_count
        interrupt_count += 1
        if interrupt_count == 1:
            LOG.info("Interrupt received, starting graceful shutdown")
            stop_event.set()
            return
        LOG.warning("Second interrupt received, forcing process exit")
        raise KeyboardInterrupt()

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):
            LOG.debug("Signal handler registration skipped for %s", sig)

    try:
        http_server.start()
        scheduler.start()
        while not stop_event.wait(timeout=0.5):
            continue
    except KeyboardInterrupt:
        forced_interrupt = True
        stop_event.set()
        LOG.warning("Keyboard interrupt received, shutting down")
    finally:
        scheduler.stop()
        http_server.stop()

    if forced_interrupt or interrupt_count > 0:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
