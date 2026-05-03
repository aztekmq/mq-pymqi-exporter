from __future__ import annotations

import tempfile
import unittest

from mq_requestreply.mq_requestreply import (
    MQRequestReplyError,
    RequestReplyConfig,
    load_request_payload,
    parse_mq_byte_id,
    validate_config,
)


class RequestReplyTests(unittest.TestCase):
    def _base_config(self, **overrides) -> RequestReplyConfig:
        values = {
            "queue_manager": "QM1",
            "channel": "DEV.APP.SVRCONN",
            "conn_name": "localhost(1415)",
            "request_queue": "APP.REQUEST",
            "reply_queue": "APP.REPLY",
            "message": "ping",
            "message_file": None,
        }
        values.update(overrides)
        return RequestReplyConfig(**values)

    def test_validate_config_requires_exactly_one_message_source(self) -> None:
        with self.assertRaises(MQRequestReplyError):
            validate_config(self._base_config(message=None, message_file=None))
        with self.assertRaises(MQRequestReplyError):
            validate_config(self._base_config(message="ping", message_file="request.txt"))

    def test_parse_mq_byte_id_pads_to_24_bytes(self) -> None:
        value = parse_mq_byte_id("A1B2")
        self.assertEqual(len(value), 24)
        self.assertEqual(value[:2], bytes.fromhex("A1B2"))

    def test_load_request_payload_reads_file_bytes(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b'{"ping":true}')
            path = handle.name
        config = self._base_config(message=None, message_file=path)
        self.assertEqual(load_request_payload(config), b'{"ping":true}')


if __name__ == "__main__":
    unittest.main()
