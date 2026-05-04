from __future__ import annotations

from pathlib import Path
import shutil
import textwrap
import unittest

from mq_exporter.config import load_exporter_config, parse_duration


class ConfigTests(unittest.TestCase):
    def test_parse_duration(self) -> None:
        self.assertEqual(parse_duration("15s"), 15.0)
        self.assertEqual(parse_duration("2m"), 120.0)
        self.assertEqual(parse_duration("1h"), 3600.0)

    def test_load_exporter_config(self) -> None:
        root = Path("tests_tmp_config")
        if root.exists():
            shutil.rmtree(root)
        (root / "qmgrs").mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))

        (root / "exporter.yaml").write_text(
            textwrap.dedent(
                """
                server:
                  port: 9200
                worker_pool:
                  max_threads: 99
                qmgr_directory: qmgrs
                """
            ).strip(),
            encoding="utf-8",
        )
        (root / "qmgrs" / "qm1.yaml").write_text(
            textwrap.dedent(
                """
                name: QM1
                poll_interval: 15s
                timeout: 10s
                connection:
                  queue_manager: QM1
                  channel: DEV.APP.SVRCONN
                  conn_name: localhost(1415)
                metrics:
                  include_topics: true
                  include_accounting: true
                  include_statistics: true
                  include_activity_trace: true
                  include_system_topic_stream: true
                  topic_patterns:
                    - SYSTEM.ADMIN.TOPIC
                  system_topic_subscription_patterns:
                    - $SYS/MQ/INFO/QMGR/{qmgr}/#
                  system_topic_max_messages_per_poll: 25
                """
            ).strip(),
            encoding="utf-8",
        )

        config = load_exporter_config(root / "exporter.yaml")

        self.assertEqual(config.server.port, 9200)
        self.assertEqual(config.worker_pool.max_threads, 50)
        self.assertEqual(len(config.queue_managers), 1)
        self.assertEqual(config.queue_managers[0].poll_interval_seconds, 15.0)
        self.assertTrue(config.queue_managers[0].metrics.include_topics)
        self.assertTrue(config.queue_managers[0].metrics.include_accounting)
        self.assertTrue(config.queue_managers[0].metrics.include_statistics)
        self.assertTrue(config.queue_managers[0].metrics.include_activity_trace)
        self.assertTrue(config.queue_managers[0].metrics.include_system_topic_stream)
        self.assertEqual(config.queue_managers[0].metrics.system_topic_subscription_patterns, ("$SYS/MQ/INFO/QMGR/{qmgr}/#",))
        self.assertEqual(config.queue_managers[0].metrics.system_topic_max_messages_per_poll, 25)


if __name__ == "__main__":
    unittest.main()
