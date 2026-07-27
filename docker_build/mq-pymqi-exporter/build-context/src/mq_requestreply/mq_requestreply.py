from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import sys
from typing import Sequence


LOG = logging.getLogger("mq_requestreply")


@dataclass(frozen=True)
class RequestReplyConfig:
    queue_manager: str
    channel: str
    conn_name: str
    queue_name: str
    user: str = ""
    password: str = ""
    message: str | None = None
    message_file: str | None = None
    encoding: str = "utf-8"
    wait_timeout_ms: int = 30000
    max_bytes: int = 65536
    expiry_ms: int = -1
    log_level: str = "INFO"


class MQRequestReplyError(RuntimeError):
    """Base exception for same-queue put/get failures."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Put one IBM MQ message and then drain all available messages from the same queue.")
    parser.add_argument("--queue-manager", default=os.environ.get("MQ_QMGR", ""), help="Queue manager name.")
    parser.add_argument("--channel", default=os.environ.get("MQ_CHANNEL", ""), help="Client channel name.")
    parser.add_argument("--conn-name", default=os.environ.get("MQ_CONN_NAME", ""), help="Connection name, for example localhost(1415).")
    parser.add_argument("--user", default=os.environ.get("MQ_USER", ""), help="MQ client username.")
    parser.add_argument("--password", default=os.environ.get("MQ_PASSWORD", ""), help="MQ client password.")
    parser.add_argument("--queue", default=os.environ.get("MQ_QUEUE", ""), help="Queue used for both put and get.")
    parser.add_argument("--request-queue", default=os.environ.get("MQ_REQUEST_QUEUE", ""), help="Compatibility alias for --queue.")
    parser.add_argument("--reply-queue", default=os.environ.get("MQ_REPLY_QUEUE", ""), help="Compatibility alias for --queue.")
    parser.add_argument("--message", default=os.environ.get("MQ_REQUEST_MESSAGE"), help="Inline message payload.")
    parser.add_argument("--message-file", default=os.environ.get("MQ_REQUEST_MESSAGE_FILE"), help="Path to a file containing the message payload.")
    parser.add_argument("--encoding", default=os.environ.get("MQ_MESSAGE_ENCODING", "utf-8"), help="Encoding for message payload text.")
    parser.add_argument("--wait-timeout-ms", default=os.environ.get("MQ_WAIT_TIMEOUT_MS", "30000"), type=int, help="How long to wait for the first message before draining the queue.")
    parser.add_argument("--max-bytes", default=os.environ.get("MQ_REPLY_MAX_BYTES", "65536"), type=int, help="Maximum payload size to read.")
    parser.add_argument("--expiry-ms", default=os.environ.get("MQ_REQUEST_EXPIRY_MS", "-1"), type=int, help="Message expiry in milliseconds. Use -1 for unlimited.")
    parser.add_argument("--log-level", default=os.environ.get("MQ_LOG_LEVEL", "INFO"), help="Logging level.")
    return parser


def args_to_config(args: argparse.Namespace) -> RequestReplyConfig:
    queue_name = _first_non_empty(
        getattr(args, "queue", ""),
        getattr(args, "request_queue", ""),
        getattr(args, "reply_queue", ""),
    )
    return RequestReplyConfig(
        queue_manager=_strip_wrapping_quotes(str(args.queue_manager).strip()),
        channel=_strip_wrapping_quotes(str(args.channel).strip()),
        conn_name=_strip_wrapping_quotes(str(args.conn_name).strip()),
        queue_name=_strip_wrapping_quotes(str(queue_name).strip()),
        user=_strip_wrapping_quotes(str(args.user).strip()),
        password=str(args.password),
        message=args.message,
        message_file=_strip_wrapping_quotes(str(args.message_file).strip()) if args.message_file else None,
        encoding=_strip_wrapping_quotes(str(args.encoding).strip()) or "utf-8",
        wait_timeout_ms=int(args.wait_timeout_ms),
        max_bytes=int(args.max_bytes),
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
            ("queue_name", config.queue_name),
        )
        if not value
    ]
    if missing:
        raise MQRequestReplyError(f"Missing required configuration values: {', '.join(missing)}.")
    if bool(config.message) == bool(config.message_file):
        raise MQRequestReplyError("Provide exactly one of --message or --message-file.")
    if config.wait_timeout_ms < 1:
        raise MQRequestReplyError("--wait-timeout-ms must be a positive integer.")
    if config.max_bytes < 1:
        raise MQRequestReplyError("--max-bytes must be a positive integer.")
    if config.expiry_ms < -1:
        raise MQRequestReplyError("--expiry-ms must be -1 or greater.")


def load_request_payload(config: RequestReplyConfig) -> bytes:
    if config.message is not None:
        return config.message.encode(config.encoding)
    assert config.message_file is not None
    return Path(config.message_file).read_bytes()


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = _strip_wrapping_quotes(str(value).strip())
        if text:
            return text
    return ""


def _mq_bytes(value: str, encoding: str = "ascii") -> bytes:
    try:
        return value.encode(encoding)
    except UnicodeEncodeError as exc:
        raise MQRequestReplyError(f"Value {value!r} cannot be encoded as {encoding} for MQMD fields.") from exc


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
        details += f" Timed out waiting for messages on {object_name!r}."
    return details


def run_request_reply(config: RequestReplyConfig) -> int:
    try:
        import pymqi  # type: ignore
    except ImportError as exc:
        raise MQRequestReplyError("pymqi is required to run mq_requestreply.py.") from exc

    payload = load_request_payload(config)
    qmgr = None
    queue = None
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

        queue_open_options = (
            getattr(pymqi.CMQC, "MQOO_OUTPUT", 0)
            | getattr(pymqi.CMQC, "MQOO_INPUT_SHARED", 0)
            | getattr(pymqi.CMQC, "MQOO_FAIL_IF_QUIESCING", 0)
        )
        try:
            queue = pymqi.Queue(qmgr, config.queue_name, queue_open_options)
        except pymqi.MQMIError as exc:
            raise MQRequestReplyError(
                format_mq_error(exc, operation="open queue", object_name=config.queue_name)
            ) from exc

        request_md = pymqi.MD()
        request_pmo = pymqi.PMO()
        request_pmo.Options = (
            getattr(pymqi.CMQC, "MQPMO_FAIL_IF_QUIESCING", 0)
            | getattr(pymqi.CMQC, "MQPMO_NEW_MSG_ID", 0)
            | getattr(pymqi.CMQC, "MQPMO_NEW_CORREL_ID", 0)
        )
        request_md.ReplyToQ = _mq_bytes(config.queue_name)
        request_md.ReplyToQMgr = _mq_bytes(config.queue_manager)
        mqfmt_string = getattr(pymqi.CMQC, "MQFMT_STRING", None)
        if mqfmt_string is not None:
            request_md.Format = mqfmt_string if isinstance(mqfmt_string, bytes) else _mq_bytes(str(mqfmt_string))
        if config.expiry_ms >= 0:
            expiry_tenths = max(1, config.expiry_ms // 100) if config.expiry_ms > 0 else 0
            request_md.Expiry = expiry_tenths

        LOG.info("Putting message to %s via %s on %s", config.queue_name, config.channel, config.conn_name)
        try:
            queue.put(payload, request_md, request_pmo)
        except pymqi.MQMIError as exc:
            raise MQRequestReplyError(
                format_mq_error(exc, operation="put message", object_name=config.queue_name)
            ) from exc
        except TypeError as exc:
            raise MQRequestReplyError(
                f"Invalid MQMD value while putting to {config.queue_name!r}: {exc}"
            ) from exc

        wait_interval = config.wait_timeout_ms
        get_options = (
            getattr(pymqi.CMQC, "MQGMO_WAIT", 0)
            | getattr(pymqi.CMQC, "MQGMO_FAIL_IF_QUIESCING", 0)
            | getattr(pymqi.CMQC, "MQGMO_CONVERT", 0)
        )
        messages: list[tuple[object, object]] = []

        LOG.info("Waiting up to %d ms for messages on %s, then draining the queue", config.wait_timeout_ms, config.queue_name)
        while True:
            reply_md = pymqi.MD()
            reply_gmo = pymqi.GMO()
            reply_gmo.Options = get_options
            reply_gmo.WaitInterval = wait_interval
            try:
                reply_bytes = queue.get(config.max_bytes, reply_md, reply_gmo)
                messages.append((reply_md, reply_bytes))
                wait_interval = 1
            except pymqi.MQMIError as exc:
                if getattr(exc, "reason", None) == 2033:
                    if messages:
                        break
                    raise MQRequestReplyError(
                        format_mq_error(exc, operation="get messages", object_name=config.queue_name)
                    ) from exc
                raise MQRequestReplyError(
                    format_mq_error(exc, operation="get messages", object_name=config.queue_name)
                ) from exc
            except TypeError as exc:
                raise MQRequestReplyError(
                    f"Invalid MQMD/GMO value while getting from {config.queue_name!r}: {exc}"
                ) from exc
    finally:
        if queue is not None:
            try:
                queue.close()
            except Exception:
                LOG.debug("Queue close failed", exc_info=True)
        if qmgr is not None:
            try:
                qmgr.disconnect()
            except Exception:
                LOG.debug("Queue manager disconnect failed", exc_info=True)

    print(f"Drained {len(messages)} message(s) from {config.queue_name}:")
    for index, (reply_md, reply_bytes) in enumerate(messages, start=1):
        print(f"Message {index}:")
        print(f"  format: {getattr(reply_md, 'Format', '')!r}")
        print(f"  message_id: {bytes(reply_md.MsgId).hex().upper()}")
        print(f"  correlation_id: {bytes(reply_md.CorrelId).hex().upper()}")
        print("  payload:")
        if isinstance(reply_bytes, bytes):
            sys.stdout.write(reply_bytes.decode(config.encoding, errors='replace'))
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
