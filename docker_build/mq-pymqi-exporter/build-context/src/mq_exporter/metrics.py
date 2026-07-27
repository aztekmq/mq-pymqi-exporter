from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import time
from typing import Iterable

from prometheus_client import CollectorRegistry, Counter, Gauge


@dataclass(frozen=True)
class MetricRecord:
    name: str
    documentation: str
    labels: dict[str, str]
    value: float


@dataclass
class _FamilyState:
    gauge: Gauge
    label_names: tuple[str, ...]
    scoped_series: dict[str, set[tuple[str, ...]]]


class MetricStore:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self._lock = RLock()
        self._families: dict[str, _FamilyState] = {}
        self._scope_metrics: dict[str, set[str]] = {}

        self.target_up = Gauge(
            "ibmmq_exporter_target_up",
            "Whether the last background poll for this queue manager succeeded.",
            ["qmgr"],
            registry=self.registry,
        )
        self.poll_duration = Gauge(
            "ibmmq_exporter_poll_duration_seconds",
            "Duration of the last background poll.",
            ["qmgr"],
            registry=self.registry,
        )
        self.last_success = Gauge(
            "ibmmq_exporter_last_success_unixtime",
            "Unix timestamp of the last successful poll.",
            ["qmgr"],
            registry=self.registry,
        )
        self.next_poll = Gauge(
            "ibmmq_exporter_next_poll_unixtime",
            "Unix timestamp of the next scheduled poll.",
            ["qmgr"],
            registry=self.registry,
        )
        self.poll_errors = Counter(
            "ibmmq_exporter_poll_errors_total",
            "Total number of background poll failures.",
            ["qmgr"],
            registry=self.registry,
        )

    def set_next_poll(self, qmgr: str, when: float) -> None:
        self.next_poll.labels(qmgr=qmgr).set(when)

    def record_success(self, qmgr: str, duration_seconds: float, records: Iterable[MetricRecord]) -> None:
        with self._lock:
            self.target_up.labels(qmgr=qmgr).set(1)
            self.poll_duration.labels(qmgr=qmgr).set(duration_seconds)
            self.last_success.labels(qmgr=qmgr).set(time())
            self._replace_scope_records(qmgr, list(records))

    def record_failure(self, qmgr: str, duration_seconds: float) -> None:
        with self._lock:
            self.target_up.labels(qmgr=qmgr).set(0)
            self.poll_duration.labels(qmgr=qmgr).set(duration_seconds)
            self.poll_errors.labels(qmgr=qmgr).inc()

    def _replace_scope_records(self, scope: str, records: list[MetricRecord]) -> None:
        grouped: dict[str, list[MetricRecord]] = {}
        for record in records:
            grouped.setdefault(record.name, []).append(record)

        prior_metrics = self._scope_metrics.get(scope, set()).copy()
        current_metrics = set(grouped)

        for metric_name in prior_metrics - current_metrics:
            self._remove_scope_from_family(metric_name, scope)

        for metric_name, metric_records in grouped.items():
            family = self._families.get(metric_name)
            label_names = tuple(metric_records[0].labels.keys())
            if family is None:
                gauge = Gauge(
                    metric_name,
                    metric_records[0].documentation,
                    list(label_names),
                    registry=self.registry,
                )
                family = _FamilyState(gauge=gauge, label_names=label_names, scoped_series={})
                self._families[metric_name] = family
            elif family.label_names != label_names:
                raise ValueError(f"Metric {metric_name} changed label names from {family.label_names} to {label_names}")

            seen: set[tuple[str, ...]] = set()
            for record in metric_records:
                label_values = tuple(record.labels[name] for name in family.label_names)
                seen.add(label_values)
                family.gauge.labels(**record.labels).set(record.value)

            for stale in family.scoped_series.get(scope, set()) - seen:
                family.gauge.remove(*stale)

            family.scoped_series[scope] = seen

        self._scope_metrics[scope] = current_metrics

    def _remove_scope_from_family(self, metric_name: str, scope: str) -> None:
        family = self._families[metric_name]
        for stale in family.scoped_series.get(scope, set()):
            family.gauge.remove(*stale)
        family.scoped_series.pop(scope, None)
