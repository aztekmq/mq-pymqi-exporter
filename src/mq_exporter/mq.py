from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from .config import QueueManagerConfig
from .metrics import MetricRecord


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MetricSpec:
    metric_name: str
    help_text: str


Q_MGR_SPECS = {
    "MQIA_PLATFORM": _MetricSpec("ibmmq_qmgr_platform", "Queue manager platform code."),
    "MQIA_COMMAND_LEVEL": _MetricSpec("ibmmq_qmgr_command_level", "Queue manager command level."),
}

QUEUE_SPECS = {
    "MQIA_CURRENT_Q_DEPTH": _MetricSpec("ibmmq_queue_current_depth", "Current queue depth."),
    "MQIA_MAX_Q_DEPTH": _MetricSpec("ibmmq_queue_max_depth", "Maximum configured queue depth."),
    "MQIA_OPEN_INPUT_COUNT": _MetricSpec("ibmmq_queue_open_input_count", "Current open input handle count."),
    "MQIA_OPEN_OUTPUT_COUNT": _MetricSpec("ibmmq_queue_open_output_count", "Current open output handle count."),
}

CHANNEL_SPECS = {
    "MQIACH_CHANNEL_STATUS": _MetricSpec("ibmmq_channel_status", "Current channel status code."),
    "MQIACH_BYTES_SENT": _MetricSpec("ibmmq_channel_bytes_sent", "Bytes sent on the channel."),
    "MQIACH_BYTES_RCVD": _MetricSpec("ibmmq_channel_bytes_received", "Bytes received on the channel."),
}


class PyMQICollector:
    def __init__(self) -> None:
        try:
            import pymqi  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pymqi is required to collect MQ metrics") from exc
        self.pymqi = pymqi

    def collect(self, config: QueueManagerConfig) -> list[MetricRecord]:
        qmgr = self._connect(config)
        try:
            pcf = self.pymqi.PCFExecute(qmgr)
            records: list[MetricRecord] = []
            if config.metrics.include_queue_manager:
                records.extend(self._collect_qmgr_metrics(config, pcf))
            if config.metrics.include_queues:
                records.extend(self._collect_queue_metrics(config, pcf))
            if config.metrics.include_channels:
                records.extend(self._collect_channel_metrics(config, pcf))
            return records
        finally:
            try:
                qmgr.disconnect()
            except Exception:
                LOG.exception("Disconnect failed for %s", config.name)

    def _connect(self, config: QueueManagerConfig):
        password = config.connection.resolved_password()
        return self.pymqi.connect(
            config.connection.queue_manager,
            config.connection.channel,
            config.connection.conn_name,
            config.connection.user,
            password,
        )

    def _collect_qmgr_metrics(self, config: QueueManagerConfig, pcf) -> list[MetricRecord]:
        records: list[MetricRecord] = []
        responses = pcf.MQCMD_INQUIRE_Q_MGR()
        for response in responses:
            for attr_name, spec in Q_MGR_SPECS.items():
                attr_id = getattr(self.pymqi.CMQC, attr_name, None)
                if attr_id is None or attr_id not in response:
                    continue
                value = self._coerce_numeric(response[attr_id])
                if value is None:
                    continue
                records.append(
                    MetricRecord(
                        name=spec.metric_name,
                        documentation=spec.help_text,
                        labels={"qmgr": config.name},
                        value=value,
                    )
                )
        return records

    def _collect_queue_metrics(self, config: QueueManagerConfig, pcf) -> list[MetricRecord]:
        records: list[MetricRecord] = []
        queue_name_attr = getattr(self.pymqi.CMQC, "MQCA_Q_NAME", None)
        queue_type_attr = getattr(self.pymqi.CMQC, "MQIA_Q_TYPE", None)
        queue_type_local = getattr(self.pymqi.CMQC, "MQQT_LOCAL", None)
        if queue_name_attr is None or queue_type_attr is None or queue_type_local is None:
            return records

        for pattern in config.metrics.queue_patterns:
            responses = pcf.MQCMD_INQUIRE_Q(
                {
                    queue_name_attr: pattern,
                    queue_type_attr: queue_type_local,
                }
            )
            for response in responses:
                queue_name = str(response.get(queue_name_attr, "")).strip()
                if not queue_name:
                    continue
                for attr_name, spec in QUEUE_SPECS.items():
                    attr_id = getattr(self.pymqi.CMQC, attr_name, None)
                    if attr_id is None or attr_id not in response:
                        continue
                    value = self._coerce_numeric(response[attr_id])
                    if value is None:
                        continue
                    records.append(
                        MetricRecord(
                            name=spec.metric_name,
                            documentation=spec.help_text,
                            labels={"qmgr": config.name, "queue": queue_name},
                            value=value,
                        )
                    )
        return records

    def _collect_channel_metrics(self, config: QueueManagerConfig, pcf) -> list[MetricRecord]:
        records: list[MetricRecord] = []
        channel_name_attr = getattr(self.pymqi.CMQCFC, "MQCACH_CHANNEL_NAME", None)
        if channel_name_attr is None:
            return records

        for pattern in config.metrics.channel_patterns:
            responses = pcf.MQCMD_INQUIRE_CHANNEL_STATUS({channel_name_attr: pattern})
            for response in responses:
                channel_name = str(response.get(channel_name_attr, "")).strip()
                if not channel_name:
                    continue
                for attr_name, spec in CHANNEL_SPECS.items():
                    attr_id = getattr(self.pymqi.CMQCFC, attr_name, None)
                    if attr_id is None or attr_id not in response:
                        continue
                    value = self._coerce_numeric(response[attr_id])
                    if value is None:
                        continue
                    records.append(
                        MetricRecord(
                            name=spec.metric_name,
                            documentation=spec.help_text,
                            labels={"qmgr": config.name, "channel": channel_name},
                            value=value,
                        )
                    )
        return records

    @staticmethod
    def _coerce_numeric(value: Any) -> float | None:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        return None
