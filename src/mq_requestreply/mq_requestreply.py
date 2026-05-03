from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import sys
from typing import Sequence


LOG = logging.getLogger("mq_requestreply")
_MQ_BYTE_ID_LENGTH = 24


@dataclass(frozen=True)
class RequestReplyConfig:
    queue_manager: str
    channel: str
    conn_name: str
    request_queue: str
    reply_queue: str
    user: str = ""
    password: str = ""
    message: str | None = None
    message_file: str | None = None
    encoding: str = "utf-8"
    wait_timeout_ms: int = 30000
    reply_max_bytes: int = 65536
    correlation_id_hex: str | None = None
    expiry_ms: int = -1
    log_level: str = "INFO"


class MQRequestReplyError(RuntimeError):
    """Base exception for request/reply failures."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send one IBM MQ request message and wait for one correlated reply.")
    parser.add_argument("--queue-manager", default=os.environ.get("MQ_QMGR", ""), help="Queue manager name.")
    parser.add_argument("--channel", default=os.environ.get("MQ_CHANNEL", ""), help="Client channel name.")
    parser.add_argument("--conn-name", default=os.environ.get("MQ_CONN_NAME", ""), help="Connection name, for example localhost(1415).")
    parser.add_argument("--user", default=os.environ.get("MQ_USER", ""), help="MQ client username.")
    parser.add_argument("--password", default=os.environ.get("MQ_PASSWORD", ""), help="MQ client password.")
    parser.add_argument("--request-queue", default=os.environ.get("MQ_REQUEST_QUEUE", ""), help="Queue that receives the request message.")
    parser.add_argument("--reply-queue", default=os.environ.get("MQ_REPLY_QUEUE", ""), help="Queue to read the correlated reply from.")
    parser.add_argument("--message", default=os.environ.get("MQ_REQUEST_MESSAGE"), help="Inline request payload.")
    parser.add_argument("--message-file", default=os.environ.get("MQ_REQUEST_MESSAGE_FILE"), help="Path to a file containing the request payload.")
    parser.add_argument("--encoding", default=os.environ.get("MQ_MESSAGE_ENCODING", "utf-8"), help="Encoding for request and reply payload text.")
    parser.add_argument("--wait-timeout-ms", default=os.environ.get("MQ_WAIT_TIMEOUT_MS", "30000"), type=int, help="How long to wait for the reply.")
    parser.add_argument("--reply-max-bytes", default=os.environ.get("MQ_REPLY_MAX_BYTES", "65536"), type=int, help="Maximum reply payload size to read.")
    parser.add_argument("--correlation-id-hex", default=os.environ.get("MQ_CORRELATION_ID_HEX"), help="Optional 48-character hex correlation id.")
    parser.add_argument("--expiry-ms", default=os.environ.get("MQ_REQUEST_EXPIRY_MS", "-1"), type=int, help="Request expiry in milliseconds. Use -1 for unlimited.")
    parser.add_argument("--log-level", default=os.environ.get("MQ_LOG_LEVEL", "INFO"), help="Logging level.")
    return parser


def args_to_config(args: argparse.Namespace) -> RequestReplyConfig:
    return RequestReplyConfig(
        queue_manager=_strip_wrapping_quotes(str(args.queue_manager).strip()),
        channel=_strip_wrapping_quotes(str(args.channel).strip()),
        conn_name=_strip_wrapping_quotes(str(args.conn_name).strip()),
        request_queue=_strip_wrapping_quotes(str(args.request_queue).strip()),
        reply_queue=_strip_wrapping_quotes(str(args.reply_queue).strip()),
        user=_strip_wrapping_quotes(str(args.user).strip()),
        password=str(args.password),
        message=args.message,
        message_file=_strip_wrapping_quotes(str(args.message_file).strip()) if args.message_file else None,
        encoding=_strip_wrapping_quotes(str(args.encoding).strip()) or "utf-8",
        wait_timeout_ms=int(args.wait_timeout_ms),
        reply_max_bytes=int(args.reply_max_bytes),
        correlation_id_hex=_strip_wrapping_quotes(str(args.correlation_id_hex).strip()) if args.correlation_id_hex else None,
        expiry_ms=int(args.expiry_ms),
        log_level=_strip_wrapping_quotes(str(args.log_level).strip()).upper() or "INFO",
    )


def validate_config(config: RequestReplyConfig) -> None:
    missing = [
        name
        for name, value in (
            ("queue_manager", config.queue_manager),
            ("channel", config.channel),
            ("conn_name", config.conn_name),
            ("request_queue", config.request_queue),
            ("reply_queue", config.reply_queue),
        )
        if not value
    ]
    if missing:
        raise MQRequestReplyError(f"Missing required configuration values: {', '.join(missing)}.")
    if bool(config.message) == bool(config.message_file):
        raise MQRequestReplyError("Provide exactly one of --message or --message-file.")
    if config.wait_timeout_ms < 1:
        raise MQRequestReplyError("--wait-timeout-ms must be a positive integer.")
    if config.reply_max_bytes < 1:
        raise MQRequestReplyError("--reply-max-bytes must be a positive integer.")
    if config.expiry_ms < -1:
        raise MQRequestReplyError("--expiry-ms must be -1 or greater.")
    if config.correlation_id_hex is not None:
        parse_mq_byte_id(config.correlation_id_hex)


def load_request_payload(config: RequestReplyConfig) -> bytes:
    if config.message is not None:
        return config.message.encode(config.encoding)
    assert config.message_file is not None
    return Path(config.message_file).read_bytes()


def parse_mq_byte_id(value: str) -> bytes:
    compact = "".join(value.split())
    if not compact:
        raise MQRequestReplyError("Correlation id hex value cannot be empty.")
    if len(compact) > _MQ_BYTE_ID_LENGTH * 2:
        raise MQRequestReplyError("Correlation id hex value cannot exceed 48 hex characters.")
    if len(compact) % 2 != 0:
        raise MQRequestReplyError("Correlation id hex value must contain an even number of characters.")
    try:
        raw = bytes.fromhex(compact)
    except ValueError as exc:
        raise MQRequestReplyError("Correlation id hex value contains non-hexadecimal characters.") from exc
    return raw.ljust(_MQ_BYTE_ID_LENGTH, b"\x00")


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def format_mq_error(exc: Exception, *, operation: str, object_name: str | None = None) -> str:
    completion_code = getattr(exc, "comp", None)
    reason_code = getattr(exc, "reason", None)
    parts = [f"IBM MQ operation {operation} failed"]
    if object_name:
        parts.append(f"object={object_name!r}")
    if isinstance(completion_code, int):
        parts.append(f"completion_code={completion_code}")
    if isinstance(reason_code, int):
        parts.append(f"reason={reason_code}")
    details = "; ".join(parts) + "."
    if reason_code == 2033 and object_name:
        details += f" Timed out waiting for a reply on {object_name!r}."
    return details


def run_request_reply(config: RequestReplyConfig) -> int:
    try:
        import pymqi  # type: ignore
    except ImportError as exc:
        raise MQRequestReplyError("pymqi is required to run mq_requestreply.py.") from exc

    payload = load_request_payload(config)
    qmgr = None
    request_queue = None
    reply_queue = None
    try:
        try:
            qmgr = pymqi.connect(
                config.queue_manager,
                config.channel,
                config.conn_name,
                config.user,
                config.password,
            )
        except pymqi.MQMIError as exc:
            raise MQRequestReplyError(
                format_mq_error(exc, operation="connect", object_name=config.queue_manager)
            ) from exc
        open_output = getattr(pymqi.CMQC, "MQOO_OUTPUT", 0)
        open_input = getattr(pymqi.CMQC, "MQOO_INPUT_SHARED", 0)
        fail_if_quiescing = getattr(pymqi.CMQC, "MQOO_FAIL_IF_QUIESCING", 0)
        try:
            request_queue = pymqi.Queue(qmgr, config.request_queue, open_output | fail_if_quiescing)
        except pymqi.MQMIError as exc:
            raise MQRequestReplyError(
                format_mq_error(exc, operation="open request queue", object_name=config.request_queue)
            ) from exc
        try:
            reply_queue = pymqi.Queue(qmgr, config.reply_queue, open_input | fail_if_quiescing)
        except pymqi.MQMIError as exc:
            raise MQRequestReplyError(
                format_mq_error(exc, operation="open reply queue", object_name=config.reply_queue)
            ) from exc

        request_md = pymqi.MD()
        request_pmo = pymqi.PMO()
        request_pmo.Options = (
            getattr(pymqi.CMQC, "MQPMO_FAIL_IF_QUIESCING", 0)
            | getattr(pymqi.CMQC, "MQPMO_NEW_MSG_ID", 0)
            | getattr(pymqi.CMQC, "MQPMO_NEW_CORREL_ID", 0)
        )
        request_md.ReplyToQ = config.reply_queue
        request_md.ReplyToQMgr = config.queue_manager
        if config.expiry_ms >= 0:
            expiry_tenths = max(1, config.expiry_ms // 100) if config.expiry_ms > 0 else 0
            request_md.Expiry = expiry_tenths
        if config.correlation_id_hex is not None:
            request_md.CorrelId = parse_mq_byte_id(config.correlation_id_hex)

        LOG.info(
            "Putting request message to %s via %s on %s",
            config.request_queue,
            config.channel,
            config.conn_name,
        )
        try:
            request_queue.put(payload, request_md, request_pmo)
        except pymqi.MQMIError as exc:
            raise MQRequestReplyError(
                format_mq_error(exc, operation="put request message", object_name=config.request_queue)
            ) from exc
        request_message_id = bytes(request_md.MsgId)
        LOG.info("Request put complete. Message id=%s", request_message_id.hex().upper())

        reply_md = pymqi.MD()
        reply_md.CorrelId = request_message_id
        reply_gmo = pymqi.GMO()
        reply_gmo.Options = (
            getattr(pymqi.CMQC, "MQGMO_WAIT", 0)
            | getattr(pymqi.CMQC, "MQGMO_FAIL_IF_QUIESCING", 0)
            | getattr(pymqi.CMQC, "MQGMO_CONVERT", 0)
        )
        reply_gmo.WaitInterval = config.wait_timeout_ms
        reply_gmo.MatchOptions = getattr(pymqi.CMQC, "MQMO_MATCH_CORREL_ID", 0)

        LOG.info(
            "Waiting up to %d ms for a reply on %s with correl id %s",
            config.wait_timeout_ms,
            config.reply_queue,
            request_message_id.hex().upper(),
        )
        try:
            reply_bytes = reply_queue.get(config.reply_max_bytes, reply_md, reply_gmo)
        except pymqi.MQMIError as exc:
            raise MQRequestReplyError(
                format_mq_error(exc, operation="get reply message", object_name=config.reply_queue)
            ) from exc
    finally:
        if reply_queue is not None:
            try:
                reply_queue.close()
            except Exception:
                LOG.debug("Reply queue close failed", exc_info=True)
        if request_queue is not None:
            try:
                request_queue.close()
            except Exception:
                LOG.debug("Request queue close failed", exc_info=True)
        if qmgr is not None:
            try:
                qmgr.disconnect()
            except Exception:
                LOG.debug("Queue manager disconnect failed", exc_info=True)

    print("Reply message metadata:")
    print(f"  format: {getattr(reply_md, 'Format', '')!r}")
    print(f"  message_id: {bytes(reply_md.MsgId).hex().upper()}")
    print(f"  correlation_id: {bytes(reply_md.CorrelId).hex().upper()}")
    print("Reply payload:")
    if isinstance(reply_bytes, bytes):
        sys.stdout.write(reply_bytes.decode(config.encoding, errors="replace"))
    else:
        sys.stdout.write(str(reply_bytes))
    sys.stdout.write("\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = args_to_config(args)

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        validate_config(config)
        return run_request_reply(config)
    except MQRequestReplyError as exc:
        LOG.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
