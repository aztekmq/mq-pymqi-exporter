from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
from typing import Any

import yaml


_DURATION_RE = re.compile(r"^(?P<value>\d+)(?P<unit>ms|s|m|h)$")


def parse_duration(value: str) -> float:
    match = _DURATION_RE.match(value.strip())
    if not match:
        raise ValueError(f"Unsupported duration format: {value!r}")
    amount = int(match.group("value"))
    unit = match.group("unit")
    scale = {
        "ms": 0.001,
        "s": 1.0,
        "m": 60.0,
        "h": 3600.0,
    }[unit]
    return amount * scale


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping at top level of {path}")
    return data


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 9157
    metrics_path: str = "/metrics"


@dataclass(frozen=True)
class WorkerPoolConfig:
    max_threads: int = 10
    scheduler_tick_seconds: float = 1.0


@dataclass(frozen=True)
class MetricsConfig:
    include_queue_manager: bool = True
    include_queues: bool = True
    include_topics: bool = False
    include_channels: bool = False
    include_accounting: bool = False
    include_statistics: bool = False
    include_activity_trace: bool = False
    include_system_topic_stream: bool = False
    queue_patterns: tuple[str, ...] = ("*",)
    topic_patterns: tuple[str, ...] = ("SYSTEM.ADMIN.TOPIC",)
    system_topic_subscription_patterns: tuple[str, ...] = ("INFO/QMGR/{qmgr}/#",)
    channel_patterns: tuple[str, ...] = ()
    accounting_queue_name: str = "SYSTEM.ADMIN.ACCOUNTING.QUEUE"
    statistics_queue_name: str = "SYSTEM.ADMIN.STATISTICS.QUEUE"
    activity_trace_queue_name: str = "SYSTEM.ADMIN.TRACE.ACTIVITY.QUEUE"
    system_topic_root_topic: str = "SYSTEM.ADMIN.TOPIC"
    system_topic_max_messages_per_poll: int = 500


@dataclass(frozen=True)
class ConnectionConfig:
    queue_manager: str
    channel: str
    conn_name: str
    user: str = ""
    password: str = ""
    password_env: str = ""
    password_file: str = ""

    def resolved_password(self) -> str:
        if self.password:
            return self.password
        if self.password_env:
            return os.environ.get(self.password_env, "")
        if self.password_file:
            return Path(self.password_file).read_text(encoding="utf-8").strip()
        return ""


@dataclass(frozen=True)
class QueueManagerConfig:
    name: str
    poll_interval_seconds: float
    timeout_seconds: float
    connection: ConnectionConfig
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    enabled: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(frozen=True)
class ExporterConfig:
    server: ServerConfig
    worker_pool: WorkerPoolConfig
    logging: LoggingConfig
    queue_managers: tuple[QueueManagerConfig, ...]


def load_exporter_config(path: str | Path) -> ExporterConfig:
    root_path = Path(path).resolve()
    root = _read_yaml(root_path)

    server_raw = root.get("server", {})
    worker_raw = root.get("worker_pool", {})
    logging_raw = root.get("logging", {})
    qmgr_dir = root.get("qmgr_directory", "config/qmgrs")

    base_dir = root_path.parent
    qmgr_path = (base_dir / qmgr_dir).resolve()
    if not qmgr_path.exists():
        raise FileNotFoundError(f"Queue manager config directory not found: {qmgr_path}")

    server = ServerConfig(
        host=str(server_raw.get("host", "0.0.0.0")),
        port=int(server_raw.get("port", 9157)),
        metrics_path=str(server_raw.get("metrics_path", "/metrics")),
    )
    worker_pool = WorkerPoolConfig(
        max_threads=min(50, int(worker_raw.get("max_threads", 10))),
        scheduler_tick_seconds=float(worker_raw.get("scheduler_tick_seconds", 1.0)),
    )
    logging_cfg = LoggingConfig(level=str(logging_raw.get("level", "INFO")).upper())

    default_poll_interval = parse_duration(str(root.get("default_poll_interval", "30s")))
    default_timeout = parse_duration(str(root.get("default_timeout", "20s")))

    qmgrs: list[QueueManagerConfig] = []
    for file_path in sorted(qmgr_path.glob("*.yaml")):
        raw = _read_yaml(file_path)
        connection_raw = raw.get("connection", {})
        metrics_raw = raw.get("metrics", {})

        connection = ConnectionConfig(
            queue_manager=str(connection_raw.get("queue_manager", raw["name"])),
            channel=str(connection_raw["channel"]),
            conn_name=str(connection_raw["conn_name"]),
            user=str(connection_raw.get("user", "")),
            password=str(connection_raw.get("password", "")),
            password_env=str(connection_raw.get("password_env", "")),
            password_file=str(connection_raw.get("password_file", "")),
        )
        metrics = MetricsConfig(
            include_queue_manager=bool(metrics_raw.get("include_queue_manager", True)),
            include_queues=bool(metrics_raw.get("include_queues", True)),
            include_topics=bool(metrics_raw.get("include_topics", False)),
            include_channels=bool(metrics_raw.get("include_channels", False)),
            include_accounting=bool(metrics_raw.get("include_accounting", False)),
            include_statistics=bool(metrics_raw.get("include_statistics", False)),
            include_activity_trace=bool(metrics_raw.get("include_activity_trace", False)),
            include_system_topic_stream=bool(metrics_raw.get("include_system_topic_stream", False)),
            queue_patterns=tuple(metrics_raw.get("queue_patterns", ["*"])),
            topic_patterns=tuple(metrics_raw.get("topic_patterns", ["SYSTEM.ADMIN.TOPIC"])),
            system_topic_subscription_patterns=tuple(metrics_raw.get("system_topic_subscription_patterns", ["INFO/QMGR/{qmgr}/#"])),
            channel_patterns=tuple(metrics_raw.get("channel_patterns", [])),
            accounting_queue_name=str(metrics_raw.get("accounting_queue_name", "SYSTEM.ADMIN.ACCOUNTING.QUEUE")),
            statistics_queue_name=str(metrics_raw.get("statistics_queue_name", "SYSTEM.ADMIN.STATISTICS.QUEUE")),
            activity_trace_queue_name=str(metrics_raw.get("activity_trace_queue_name", "SYSTEM.ADMIN.TRACE.ACTIVITY.QUEUE")),
            system_topic_root_topic=str(metrics_raw.get("system_topic_root_topic", "SYSTEM.ADMIN.TOPIC")),
            system_topic_max_messages_per_poll=int(metrics_raw.get("system_topic_max_messages_per_poll", 500)),
        )
        qmgrs.append(
            QueueManagerConfig(
                name=str(raw["name"]),
                enabled=bool(raw.get("enabled", True)),
                poll_interval_seconds=parse_duration(str(raw.get("poll_interval", f"{int(default_poll_interval)}s"))),
                timeout_seconds=parse_duration(str(raw.get("timeout", f"{int(default_timeout)}s"))),
                connection=connection,
                metrics=metrics,
            )
        )

    if not qmgrs:
        raise ValueError(f"No queue manager yaml files found under {qmgr_path}")

    return ExporterConfig(
        server=server,
        worker_pool=worker_pool,
        logging=logging_cfg,
        queue_managers=tuple(qmgrs),
    )
