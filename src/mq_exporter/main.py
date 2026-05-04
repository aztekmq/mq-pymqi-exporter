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


def _startup_target_lines(config) -> list[str]:
    accounting_enabled = any(getattr(qmgr.metrics, "include_accounting", False) for qmgr in getattr(config, "queue_managers", ()))
    statistics_enabled = any(getattr(qmgr.metrics, "include_statistics", False) for qmgr in getattr(config, "queue_managers", ()))
    activity_enabled = any(getattr(qmgr.metrics, "include_activity_trace", False) for qmgr in getattr(config, "queue_managers", ()))
    system_topic_stream_enabled = any(getattr(qmgr.metrics, "include_system_topic_stream", False) for qmgr in getattr(config, "queue_managers", ()))
    collector_mode = "pyMQI PCF polling plus admin queue draining" if (accounting_enabled or statistics_enabled or activity_enabled or system_topic_stream_enabled) else "pyMQI PCF polling only"
    lines = [
        f"Collector mode: {collector_mode}.",
        "MQ objects used by the exporter for metric polling:",
        "  PCF command queue: SYSTEM.ADMIN.COMMAND.QUEUE",
        "  PCF reply model queue: SYSTEM.DEFAULT.MODEL.QUEUE",
    ]
    for qmgr in getattr(config, "queue_managers", ()):
        queue_patterns = ", ".join(qmgr.metrics.queue_patterns) if qmgr.metrics.include_queues else "<disabled>"
        topic_patterns = ", ".join(getattr(qmgr.metrics, "topic_patterns", ())) if getattr(qmgr.metrics, "include_topics", False) else "<disabled>"
        system_topic_patterns = ", ".join(getattr(qmgr.metrics, "system_topic_subscription_patterns", ())) if getattr(qmgr.metrics, "include_system_topic_stream", False) else "<disabled>"
        channel_patterns = ", ".join(qmgr.metrics.channel_patterns) if qmgr.metrics.include_channels else "<disabled>"
        lines.extend(
            [
                (
                    f"  qmgr={qmgr.name} connect={qmgr.connection.queue_manager} "
                    f"channel={qmgr.connection.channel} conn_name={qmgr.connection.conn_name} user={qmgr.connection.user or '<blank>'}"
                ),
                f"    queue manager metrics: {'enabled' if qmgr.metrics.include_queue_manager else 'disabled'}",
                f"    queue inquiry patterns: {queue_patterns}",
                f"    topic inquiry patterns: {topic_patterns}",
                f"    system topic subscription patterns: {system_topic_patterns}",
                (
                    f"    system topic diagnostics: "
                    f"{'enabled' if getattr(qmgr.metrics, 'system_topic_diagnostics', False) else 'disabled'}"
                ),
                (
                    f"    system topic startup probe window: "
                    f"{getattr(qmgr.metrics, 'system_topic_startup_probe_window_seconds', 15.0)}s "
                    f"interval={getattr(qmgr.metrics, 'system_topic_startup_probe_interval_seconds', 5.0)}s"
                ),
                f"    channel inquiry patterns: {channel_patterns}",
                (
                    f"    accounting queue drain: {'enabled' if getattr(qmgr.metrics, 'include_accounting', False) else 'disabled'} "
                    f"({getattr(qmgr.metrics, 'accounting_queue_name', 'SYSTEM.ADMIN.ACCOUNTING.QUEUE')})"
                ),
                (
                    f"    statistics queue drain: {'enabled' if getattr(qmgr.metrics, 'include_statistics', False) else 'disabled'} "
                    f"({getattr(qmgr.metrics, 'statistics_queue_name', 'SYSTEM.ADMIN.STATISTICS.QUEUE')})"
                ),
                (
                    f"    activity trace queue drain: {'enabled' if getattr(qmgr.metrics, 'include_activity_trace', False) else 'disabled'} "
                    f"({getattr(qmgr.metrics, 'activity_trace_queue_name', 'SYSTEM.ADMIN.TRACE.ACTIVITY.QUEUE')})"
                ),
                (
                    f"    system topic stream drain: {'enabled' if getattr(qmgr.metrics, 'include_system_topic_stream', False) else 'disabled'} "
                    f"({getattr(qmgr.metrics, 'system_topic_root_topic', 'SYSTEM.ADMIN.TOPIC')})"
                ),
            ]
        )
    lines.extend(
        [
            "IBM MQ objects that must be enabled if you want admin/accounting/activity data generated on the queue manager side:",
            "  SYSTEM.ADMIN.ACCOUNTING.QUEUE",
            "  SYSTEM.ADMIN.STATISTICS.QUEUE",
            "  SYSTEM.ADMIN.QMGR.EVENT",
            "  SYSTEM.ADMIN.PERF.EVENT",
            "  SYSTEM.ADMIN.CHANNEL.EVENT",
            "  SYSTEM.ADMIN.COMMAND.EVENT",
            "  SYSTEM.ADMIN.CONFIG.EVENT",
            "  SYSTEM.ADMIN.ACTIVITY.QUEUE",
            "  SYSTEM.ADMIN.TRACE.ACTIVITY.QUEUE",
            "  SYSTEM.ADMIN.TOPIC",
        ]
    )
    return lines


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

    for line in _startup_target_lines(config):
        LOG.info(line)

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
        close_collector = getattr(collector, "close", None)
        if callable(close_collector):
            close_collector()

    if forced_interrupt or interrupt_count > 0:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
