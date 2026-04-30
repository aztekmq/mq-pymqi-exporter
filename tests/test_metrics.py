from __future__ import annotations

import unittest

try:
    from prometheus_client import generate_latest
except ImportError:  # pragma: no cover - environment dependent
    generate_latest = None

if generate_latest is not None:
    from mq_exporter.metrics import MetricRecord, MetricStore


@unittest.skipIf(generate_latest is None, "prometheus_client is not installed")
class MetricStoreTests(unittest.TestCase):
    def test_replace_scope_records_removes_stale_series(self) -> None:
        store = MetricStore()
        store.record_success(
            "QM1",
            0.2,
            [
                MetricRecord(
                    name="ibmmq_queue_current_depth",
                    documentation="Current queue depth.",
                    labels={"qmgr": "QM1", "queue": "Q1"},
                    value=5.0,
                )
            ],
        )
        store.record_success("QM1", 0.1, [])
        payload = generate_latest(store.registry).decode("utf-8")
        self.assertNotIn('queue="Q1"', payload)


if __name__ == "__main__":
    unittest.main()
