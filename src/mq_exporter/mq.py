from __future__ import annotations

from dataclasses import dataclass
import logging
from collections.abc import Iterable
from threading import RLock
from typing import Any
from xml.etree import ElementTree

from .config import QueueManagerConfig
from .metrics import MetricRecord


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MetricSpec:
    metric_name: str
    help_text: str


@dataclass(frozen=True)
class _DescriptorMetricSpec:
    metric_name: str
    help_text: str
    preferred_selectors: tuple[str, ...] = ()


@dataclass
class _CollectorSession:
    qmgr: Any
    subscriptions: list[Any]


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

TOPIC_STATUS_SPECS = {
    "MQIA_PUB_COUNT": _MetricSpec("ibmmq_topic_publishers", "Current number of publishers on the topic."),
    "MQIA_SUB_COUNT": _MetricSpec("ibmmq_topic_subscriptions", "Current number of subscriptions on the topic."),
    "MQIA_INHIBIT_PUB": _MetricSpec("ibmmq_topic_inhibit_publications", "Whether publications are inhibited on the topic."),
    "MQIA_INHIBIT_SUB": _MetricSpec("ibmmq_topic_inhibit_subscriptions", "Whether subscriptions are inhibited on the topic."),
    "MQIA_DURABLE_SUB": _MetricSpec("ibmmq_topic_durable_subscriptions", "Whether durable subscriptions are allowed on the topic."),
}

CHANNEL_SPECS = {
    "MQIACH_CHANNEL_STATUS": _MetricSpec("ibmmq_channel_status", "Current channel status code."),
    "MQIACH_BYTES_SENT": _MetricSpec("ibmmq_channel_bytes_sent", "Bytes sent on the channel."),
    "MQIACH_BYTES_RCVD": _MetricSpec("ibmmq_channel_bytes_received", "Bytes received on the channel."),
}

ACCOUNTING_SPECS = {
    "MQIAMO_PUTS": _MetricSpec("ibmmq_accounting_puts", "Puts observed in IBM MQ accounting messages during the last poll."),
    "MQIAMO_GETS": _MetricSpec("ibmmq_accounting_gets", "Gets observed in IBM MQ accounting messages during the last poll."),
    "MQIAMO_PUT1S": _MetricSpec("ibmmq_accounting_put1s", "Put1 operations observed in IBM MQ accounting messages during the last poll."),
    "MQIAMO_BROWSES": _MetricSpec("ibmmq_accounting_browses", "Browse operations observed in IBM MQ accounting messages during the last poll."),
    "MQIAMO_TOPIC_PUTS": _MetricSpec("ibmmq_accounting_topic_puts", "Topic puts observed in IBM MQ accounting messages during the last poll."),
    "MQIAMO_SUBS_DUR": _MetricSpec("ibmmq_accounting_subscriptions_durable", "Durable subscriptions observed in IBM MQ accounting messages during the last poll."),
    "MQIAMO_SUBS_NDUR": _MetricSpec("ibmmq_accounting_subscriptions_nondurable", "Non-durable subscriptions observed in IBM MQ accounting messages during the last poll."),
    "MQIAMO64_GET_BYTES": _MetricSpec("ibmmq_accounting_get_bytes", "Bytes read as observed in IBM MQ accounting messages during the last poll."),
    "MQIAMO64_PUT_BYTES": _MetricSpec("ibmmq_accounting_put_bytes", "Bytes written as observed in IBM MQ accounting messages during the last poll."),
    "MQIAMO64_TOPIC_PUT_BYTES": _MetricSpec("ibmmq_accounting_topic_put_bytes", "Topic put bytes observed in IBM MQ accounting messages during the last poll."),
}

STATISTICS_SPECS = {
    "MQIAMO_PUTS": _MetricSpec("ibmmq_statistics_puts", "Puts observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO_GETS": _MetricSpec("ibmmq_statistics_gets", "Gets observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO_PUT1S": _MetricSpec("ibmmq_statistics_put1s", "Put1 operations observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO_BROWSES": _MetricSpec("ibmmq_statistics_browses", "Browse operations observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO_PUTS_FAILED": _MetricSpec("ibmmq_statistics_puts_failed", "Failed put attempts observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO_GETS_FAILED": _MetricSpec("ibmmq_statistics_gets_failed", "Failed get attempts observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO_PUT1S_FAILED": _MetricSpec("ibmmq_statistics_put1s_failed", "Failed put1 attempts observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO_BROWSES_FAILED": _MetricSpec("ibmmq_statistics_browses_failed", "Failed browse attempts observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO_MSGS_EXPIRED": _MetricSpec("ibmmq_statistics_messages_expired", "Expired messages observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO_MSGS_NOT_QUEUED": _MetricSpec("ibmmq_statistics_messages_not_queued", "Messages bypassing the queue during the last poll."),
    "MQIAMO_MSGS_PURGED": _MetricSpec("ibmmq_statistics_messages_purged", "Purged messages observed during the last poll."),
    "MQIAMO64_PUT_BYTES": _MetricSpec("ibmmq_statistics_put_bytes", "Bytes written as observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO64_GET_BYTES": _MetricSpec("ibmmq_statistics_get_bytes", "Bytes read as observed in IBM MQ statistics messages during the last poll."),
    "MQIAMO64_BROWSE_BYTES": _MetricSpec("ibmmq_statistics_browse_bytes", "Browse bytes observed in IBM MQ statistics messages during the last poll."),
}

ADMIN_QUEUE_MESSAGE_SPECS = {
    "accounting": _MetricSpec("ibmmq_accounting_messages_consumed", "Accounting messages consumed from the accounting queue during the last poll."),
    "statistics": _MetricSpec("ibmmq_statistics_messages_consumed", "Statistics messages consumed from the statistics queue during the last poll."),
    "activity_trace": _MetricSpec("ibmmq_activity_trace_messages_consumed", "Activity trace messages consumed from the activity trace queue during the last poll."),
}

ACTIVITY_OPERATION_SPEC = _MetricSpec(
    "ibmmq_activity_operations",
    "IBM MQ activity operations consumed from the activity trace queue during the last poll.",
)

SYSTEM_TOPIC_STREAM_COUNT_SPEC = _MetricSpec(
    "ibmmq_system_topic_messages_consumed",
    "System topic publications consumed from the managed subscription stream during the last poll.",
)
SYSTEM_TOPIC_PUBLICATION_COUNT_SPEC = _MetricSpec(
    "ibmmq_system_topic_publications",
    "System topic publications observed during the last poll.",
)
SYSTEM_TOPIC_PUBLICATION_BYTES_SPEC = _MetricSpec(
    "ibmmq_system_topic_publication_bytes",
    "System topic publication bytes observed during the last poll.",
)

_SYSTEM_TOPIC_KNOWN_CLASSES = {"CPU", "DISK", "STATMQI", "STATQ", "STATAPP"}
_SYSTEM_TOPIC_SELECTOR_PREFIXES = (
    "MQIAMO64_",
    "MQIAMO_",
    "MQIACH_",
    "MQIACF_",
    "MQCACF_",
    "MQIA_",
    "MQCA_",
)

_MICROSECOND_SELECTORS = {
    "MQIAMO64_MONITOR_INTERVAL",
    "MQIAMO64_Q_TIME_AVG",
    "MQIAMO64_Q_TIME_MAX",
    "MQIAMO64_Q_TIME_MIN",
    "MQIAMO64_AVG_Q_TIME",
    "MQIAMO_Q_TIME_AVG",
    "MQIAMO_Q_TIME_MAX",
    "MQIAMO_Q_TIME_MIN",
    "MQIAMO_AVG_Q_TIME",
}

_SYSTEM_TOPIC_METADATA_SELECTORS = {
    "MQIAMO_MONITOR_CLASS",
    "MQIAMO_MONITOR_TYPE",
    "MQIAMO_MONITOR_UNIT",
    "MQIAMO_MONITOR_DATATYPE",
    "MQIAMO_MONITOR_ELEMENT",
    "MQIAMO_MONITOR_FLAGS",
    "MQIAMO_MONITOR_DELTA",
    "MQIAMO_MONITOR_GB",
    "MQIAMO_MONITOR_MB",
    "MQIAMO_MONITOR_KB",
    "MQIAMO_MONITOR_HUNDREDTHS",
    "MQIAMO_MONITOR_MICROSEC",
    "MQIACF_OBJECT_TYPE",
}

_EXPLICIT_SYSTEM_TOPIC_METRICS: dict[tuple[str, str], _MetricSpec] = {
    ("STATQ", "MQIAMO_OPENS"): _MetricSpec("ibmmq_statq_mqopen_total", "Interval total MQOPEN calls against the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_CLOSES"): _MetricSpec("ibmmq_statq_mqclose_total", "Interval total MQCLOSE calls against the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_INQS"): _MetricSpec("ibmmq_statq_mqinq_total", "Interval total MQINQ calls against the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_SETS"): _MetricSpec("ibmmq_statq_mqset_total", "Interval total MQSET calls against the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_PUTS"): _MetricSpec("ibmmq_statq_messages_put_total", "Interval total messages put to the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_GETS"): _MetricSpec("ibmmq_statq_messages_got_total", "Interval total destructive gets from the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_BROWSES"): _MetricSpec("ibmmq_statq_messages_browsed_total", "Interval total browse operations on the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_PUT1S"): _MetricSpec("ibmmq_statq_put1_total", "Interval total MQPUT1 operations on the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_PUTS_FAILED"): _MetricSpec("ibmmq_statq_put_failures_total", "Interval total failed put operations on the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_GETS_FAILED"): _MetricSpec("ibmmq_statq_get_failures_total", "Interval total failed destructive get operations on the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_BROWSES_FAILED"): _MetricSpec("ibmmq_statq_browse_failures_total", "Interval total failed browse operations on the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_PUT1S_FAILED"): _MetricSpec("ibmmq_statq_put1_failures_total", "Interval total failed MQPUT1 operations on the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO64_PUT_BYTES"): _MetricSpec("ibmmq_statq_put_bytes_total", "Interval total bytes written to the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO64_GET_BYTES"): _MetricSpec("ibmmq_statq_get_bytes_total", "Interval total bytes read by destructive gets from the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO64_BROWSE_BYTES"): _MetricSpec("ibmmq_statq_browse_bytes_total", "Interval total bytes read by browse operations from the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_MSGS_EXPIRED"): _MetricSpec("ibmmq_statq_messages_expired_total", "Interval total expired messages for the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO_MSGS_PURGED"): _MetricSpec("ibmmq_statq_queue_purges_total", "Interval total queue purge operations during the published monitoring interval."),
    ("STATQ", "MQIAMO_MSGS_NOT_QUEUED"): _MetricSpec("ibmmq_statq_messages_not_queued_total", "Interval total messages that bypassed the queue during the published monitoring interval."),
    ("STATQ", "MQIAMO64_Q_TIME_AVG"): _MetricSpec("ibmmq_statq_queue_time_average_seconds", "Average time a message spent on the queue during the published monitoring interval, in seconds."),
    ("STATQ", "MQIAMO64_Q_TIME_MAX"): _MetricSpec("ibmmq_statq_queue_time_max_seconds", "Maximum time a message spent on the queue during the published monitoring interval, in seconds."),
    ("STATQ", "MQIAMO64_Q_TIME_MIN"): _MetricSpec("ibmmq_statq_queue_time_min_seconds", "Minimum time a message spent on the queue during the published monitoring interval, in seconds."),
    ("STATQ", "MQIAMO_Q_MAX_DEPTH"): _MetricSpec("ibmmq_statq_queue_depth_high_watermark", "Highest queue depth observed during the published monitoring interval."),
    ("STATQ", "MQIAMO_Q_MIN_DEPTH"): _MetricSpec("ibmmq_statq_queue_depth_low_watermark", "Lowest queue depth observed during the published monitoring interval."),
    ("STATQ", "MQIA_CURRENT_Q_DEPTH"): _MetricSpec("ibmmq_statq_queue_depth_current", "Queue depth captured at the end of the published monitoring interval."),
    ("STATQ", "MQIA_MAX_Q_DEPTH"): _MetricSpec("ibmmq_statq_queue_depth_max_configured", "Configured MAXDEPTH for the queue."),
    ("STATQ", "MQIA_OPEN_INPUT_COUNT"): _MetricSpec("ibmmq_statq_open_input_handles_current", "Open input handle count captured at the end of the published monitoring interval."),
    ("STATQ", "MQIA_OPEN_OUTPUT_COUNT"): _MetricSpec("ibmmq_statq_open_output_handles_current", "Open output handle count captured at the end of the published monitoring interval."),
    ("STATQ", "MQIA_Q_DEPTH_HIGH_LIMIT"): _MetricSpec("ibmmq_statq_queue_depth_high_limit", "Configured high-depth event limit for the queue."),
    ("STATQ", "MQIA_Q_DEPTH_LOW_LIMIT"): _MetricSpec("ibmmq_statq_queue_depth_low_limit", "Configured low-depth event limit for the queue."),
    ("STATQ", "MQIAMO64_MONITOR_INTERVAL"): _MetricSpec("ibmmq_statq_monitor_interval_seconds", "Length of the STATQ published monitoring interval in seconds."),

    ("STATMQI", "MQIAMO_CONNS"): _MetricSpec("ibmmq_statmqi_mqconn_mqconnx_total", "Interval total MQCONN and MQCONNX calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_CONNS_FAILED"): _MetricSpec("ibmmq_statmqi_mqconn_mqconnx_failures_total", "Interval total failed MQCONN and MQCONNX calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_CONNS_MAX"): _MetricSpec("ibmmq_statmqi_connections_high_watermark", "Concurrent connection high-water mark captured for the published monitoring interval."),
    ("STATMQI", "MQIAMO_DISCS"): _MetricSpec("ibmmq_statmqi_mqdisc_total", "Interval total MQDISC calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_DISCS_IMPLICIT"): _MetricSpec("ibmmq_statmqi_implicit_disconnect_total", "Interval total implicit disconnects during the published monitoring interval."),
    ("STATMQI", "MQIAMO_OPENS"): _MetricSpec("ibmmq_statmqi_mqopen_total", "Interval total MQOPEN calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_OPENS_FAILED"): _MetricSpec("ibmmq_statmqi_mqopen_failures_total", "Interval total failed MQOPEN calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_CLOSES"): _MetricSpec("ibmmq_statmqi_mqclose_total", "Interval total MQCLOSE calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_CLOSES_FAILED"): _MetricSpec("ibmmq_statmqi_mqclose_failures_total", "Interval total failed MQCLOSE calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_INQS"): _MetricSpec("ibmmq_statmqi_mqinq_total", "Interval total MQINQ calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_INQS_FAILED"): _MetricSpec("ibmmq_statmqi_mqinq_failures_total", "Interval total failed MQINQ calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_SETS"): _MetricSpec("ibmmq_statmqi_mqset_total", "Interval total MQSET calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_SETS_FAILED"): _MetricSpec("ibmmq_statmqi_mqset_failures_total", "Interval total failed MQSET calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_PUTS"): _MetricSpec("ibmmq_statmqi_mqput_mqput1_total", "Interval total MQPUT and MQPUT1 calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_GETS"): _MetricSpec("ibmmq_statmqi_destructive_get_total", "Interval total destructive MQGET calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_BROWSES"): _MetricSpec("ibmmq_statmqi_browse_total", "Interval total browse operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_PUT1S"): _MetricSpec("ibmmq_statmqi_mqput1_total", "Interval total MQPUT1 calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_BROWSES_FAILED"): _MetricSpec("ibmmq_statmqi_browse_failures_total", "Interval total failed browse operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_STATS"): _MetricSpec("ibmmq_statmqi_mqstat_total", "Interval total MQSTAT calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_STATS_FAILED"): _MetricSpec("ibmmq_statmqi_mqstat_failures_total", "Interval total failed MQSTAT calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_CBS"): _MetricSpec("ibmmq_statmqi_mqcb_total", "Interval total MQCB calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_CBS_FAILED"): _MetricSpec("ibmmq_statmqi_mqcb_failures_total", "Interval total failed MQCB calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_CTLS"): _MetricSpec("ibmmq_statmqi_mqctl_total", "Interval total MQCTL calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_COMMITS"): _MetricSpec("ibmmq_statmqi_commit_total", "Interval total commit operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_BACKOUTS"): _MetricSpec("ibmmq_statmqi_rollback_total", "Interval total rollback operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_SUBS_NDUR"): _MetricSpec("ibmmq_statmqi_non_durable_subscription_create_total", "Interval total non-durable subscription create operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_SUBS_DUR"): _MetricSpec("ibmmq_statmqi_durable_subscription_create_total", "Interval total durable subscription create operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_SUBS_FAILED"): _MetricSpec("ibmmq_statmqi_subscription_create_alter_resume_failures_total", "Interval total failed create, alter, or resume subscription operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_UNSUBS_DUR"): _MetricSpec("ibmmq_statmqi_durable_subscription_delete_total", "Interval total durable subscription delete operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_UNSUBS_NDUR"): _MetricSpec("ibmmq_statmqi_non_durable_subscription_delete_total", "Interval total non-durable subscription delete operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_UNSUBS_FAILED"): _MetricSpec("ibmmq_statmqi_subscription_delete_failures_total", "Interval total failed subscription delete operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_TOPIC_PUTS"): _MetricSpec("ibmmq_statmqi_topic_mqput_mqput1_total", "Interval total topic MQPUT and MQPUT1 calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_TOPIC_PUT1S"): _MetricSpec("ibmmq_statmqi_topic_mqput1_total", "Interval total topic MQPUT1 calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_TOPIC_PUTS_FAILED"): _MetricSpec("ibmmq_statmqi_topic_put_failures_total", "Interval total failed topic MQPUT and MQPUT1 calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_TOPIC_PUT1S_FAILED"): _MetricSpec("ibmmq_statmqi_topic_put1_failures_total", "Interval total failed topic MQPUT1 calls during the published monitoring interval."),
    ("STATMQI", "MQIAMO_MSGS_SENT"): _MetricSpec("ibmmq_statmqi_published_to_subscribers_total", "Interval total publications delivered to subscribers during the published monitoring interval."),
    ("STATMQI", "MQIAMO_MSGS_EXPIRED"): _MetricSpec("ibmmq_statmqi_expired_message_total", "Interval total expired messages during the published monitoring interval."),
    ("STATMQI", "MQIAMO_MSGS_PURGED"): _MetricSpec("ibmmq_statmqi_purged_queue_total", "Interval total queue purge operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_PUTS_FAILED"): _MetricSpec("ibmmq_statmqi_put_failures_total", "Interval total failed put operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO_GETS_FAILED"): _MetricSpec("ibmmq_statmqi_get_failures_total", "Interval total failed destructive get operations during the published monitoring interval."),
    ("STATMQI", "MQIAMO64_PUT_BYTES"): _MetricSpec("ibmmq_statmqi_put_bytes_total", "Interval total bytes written by MQPUT and MQPUT1 during the published monitoring interval."),
    ("STATMQI", "MQIAMO64_GET_BYTES"): _MetricSpec("ibmmq_statmqi_get_bytes_total", "Interval total bytes read by destructive gets during the published monitoring interval."),
    ("STATMQI", "MQIAMO64_TOPIC_PUT_BYTES"): _MetricSpec("ibmmq_statmqi_topic_put_bytes_total", "Interval total bytes written by topic MQPUT and MQPUT1 during the published monitoring interval."),
    ("STATMQI", "MQIAMO64_PUBLISH_MSG_BYTES"): _MetricSpec("ibmmq_statmqi_published_to_subscribers_bytes_total", "Interval total bytes published to subscribers during the published monitoring interval."),
    ("STATMQI", "MQIAMO64_MONITOR_INTERVAL"): _MetricSpec("ibmmq_statmqi_monitor_interval_seconds", "Length of the STATMQI published monitoring interval in seconds."),

    ("STATAPP", "MQIAMO_CONNS"): _MetricSpec("ibmmq_statapp_mqconn_mqconnx_total", "Interval total MQCONN and MQCONNX calls attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_DISCS"): _MetricSpec("ibmmq_statapp_mqdisc_total", "Interval total MQDISC calls attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_OPENS"): _MetricSpec("ibmmq_statapp_mqopen_total", "Interval total MQOPEN calls attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_CLOSES"): _MetricSpec("ibmmq_statapp_mqclose_total", "Interval total MQCLOSE calls attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_INQS"): _MetricSpec("ibmmq_statapp_mqinq_total", "Interval total MQINQ calls attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_SETS"): _MetricSpec("ibmmq_statapp_mqset_total", "Interval total MQSET calls attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_PUTS"): _MetricSpec("ibmmq_statapp_messages_put_total", "Interval total messages put by the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_GETS"): _MetricSpec("ibmmq_statapp_messages_got_total", "Interval total destructive gets by the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_BROWSES"): _MetricSpec("ibmmq_statapp_messages_browsed_total", "Interval total browse operations by the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_BROWSES_FAILED"): _MetricSpec("ibmmq_statapp_browse_failures_total", "Interval total failed browse operations attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_PUTS_FAILED"): _MetricSpec("ibmmq_statapp_put_failures_total", "Interval total failed put operations attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_GETS_FAILED"): _MetricSpec("ibmmq_statapp_get_failures_total", "Interval total failed destructive get operations attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_COMMITS"): _MetricSpec("ibmmq_statapp_commit_total", "Interval total commit operations attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_BACKOUTS"): _MetricSpec("ibmmq_statapp_rollback_total", "Interval total rollback operations attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_TOPIC_PUTS"): _MetricSpec("ibmmq_statapp_topic_put_total", "Interval total topic publish operations attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO_TOPIC_PUTS_FAILED"): _MetricSpec("ibmmq_statapp_topic_put_failures_total", "Interval total failed topic publish operations attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO64_PUT_BYTES"): _MetricSpec("ibmmq_statapp_put_bytes_total", "Interval total bytes written by the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO64_GET_BYTES"): _MetricSpec("ibmmq_statapp_get_bytes_total", "Interval total bytes read by the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO64_TOPIC_PUT_BYTES"): _MetricSpec("ibmmq_statapp_topic_put_bytes_total", "Interval total topic publish bytes attributed to the application during the published monitoring interval."),
    ("STATAPP", "MQIAMO64_MONITOR_INTERVAL"): _MetricSpec("ibmmq_statapp_monitor_interval_seconds", "Length of the STATAPP published monitoring interval in seconds."),

    ("CPU", "MQIAMO64_MONITOR_INTERVAL"): _MetricSpec("ibmmq_cpu_monitor_interval_seconds", "Length of the CPU published monitoring interval in seconds."),
    ("DISK", "MQIAMO64_MONITOR_INTERVAL"): _MetricSpec("ibmmq_disk_monitor_interval_seconds", "Length of the DISK published monitoring interval in seconds."),
}

_DESCRIPTOR_SYSTEM_TOPIC_METRICS: dict[tuple[str, str], _DescriptorMetricSpec] = {
    ("STATQ", "open browse count"): _DescriptorMetricSpec(
        "ibmmq_statq_open_browse_handles_current",
        "Open browse handle count captured at the end of the published monitoring interval.",
    ),
    ("STATQ", "open publish count"): _DescriptorMetricSpec(
        "ibmmq_statq_open_publish_handles_current",
        "Open publish handle count captured at the end of the published monitoring interval.",
    ),
    ("STATQ", "seek get count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_total",
        "Interval total MQGET searches performed on the queue during the published monitoring interval.",
    ),
    ("STATQ", "msg not found count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_not_found_total",
        "Interval total MQGET searches that did not find a message during the published monitoring interval.",
    ),
    ("STATQ", "msg examine count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_examined_total",
        "Interval total messages examined by MQGET searches during the published monitoring interval.",
    ),
    ("STATQ", "intran get skipped count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_in_transaction_skipped_total",
        "Interval total messages skipped by MQGET searches because they were locked by an uncommitted get.",
    ),
    ("STATQ", "put skipped count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_uncommitted_put_skipped_total",
        "Interval total messages skipped by MQGET searches because they were put in an uncommitted transaction.",
    ),
    ("STATQ", "selection mismatch count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_selection_mismatch_total",
        "Interval total messages rejected by selector mismatch during MQGET searches.",
    ),
    ("STATQ", "correlid mismatch short count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_correlid_hash_mismatch_total",
        "Interval total messages skipped by MQGET searches because the CorrelId quick hash did not match.",
    ),
    ("STATQ", "correlid mismatch long count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_correlid_full_mismatch_total",
        "Interval total messages skipped by MQGET searches because the full CorrelId comparison did not match.",
    ),
    ("STATQ", "msgid mismatch count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_msgid_mismatch_total",
        "Interval total messages skipped by MQGET searches because MsgId did not match.",
    ),
    ("STATQ", "load msg dtl count"): _DescriptorMetricSpec(
        "ibmmq_statq_get_search_load_message_detail_total",
        "Interval total message records loaded from queue storage to complete MQGET match evaluation.",
    ),

    ("CPU", "user cpu time percentage"): _DescriptorMetricSpec(
        "ibmmq_cpu_user_time_percentage",
        "Average user CPU time percentage for the platform over the published monitoring interval.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("CPU", "system cpu time percentage"): _DescriptorMetricSpec(
        "ibmmq_cpu_system_time_percentage",
        "Average system CPU time percentage for the platform over the published monitoring interval.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("CPU", "cpu load one minute average"): _DescriptorMetricSpec(
        "ibmmq_cpu_load_one_minute_average",
        "One-minute CPU load average for the platform.",
    ),
    ("CPU", "cpu load five minute average"): _DescriptorMetricSpec(
        "ibmmq_cpu_load_five_minute_average",
        "Five-minute CPU load average for the platform.",
    ),
    ("CPU", "cpu load fifteen minute average"): _DescriptorMetricSpec(
        "ibmmq_cpu_load_fifteen_minute_average",
        "Fifteen-minute CPU load average for the platform.",
    ),
    ("CPU", "ram free percentage"): _DescriptorMetricSpec(
        "ibmmq_cpu_ram_free_percentage",
        "Current free RAM percentage for the platform.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("CPU", "ram total bytes"): _DescriptorMetricSpec(
        "ibmmq_cpu_ram_total_bytes",
        "Current total RAM bytes for the platform.",
        ("MQIAMO64_BYTES",),
    ),
    ("CPU", "user cpu time percentage estimate for queue manager"): _DescriptorMetricSpec(
        "ibmmq_qmgr_cpu_user_time_percentage",
        "Average user CPU time percentage estimate for the queue manager over the published monitoring interval.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("CPU", "system cpu time percentage estimate for queue manager"): _DescriptorMetricSpec(
        "ibmmq_qmgr_cpu_system_time_percentage",
        "Average system CPU time percentage estimate for the queue manager over the published monitoring interval.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("CPU", "ram total bytes estimate for queue manager"): _DescriptorMetricSpec(
        "ibmmq_qmgr_ram_total_bytes",
        "Current RAM bytes estimate for the queue manager.",
        ("MQIAMO64_BYTES",),
    ),

    ("DISK", "mq errors file system bytes in use"): _DescriptorMetricSpec(
        "ibmmq_qmgr_errors_file_system_in_use_bytes",
        "Current MQ errors file system bytes in use.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "mq errors file system free space"): _DescriptorMetricSpec(
        "ibmmq_qmgr_errors_file_system_free_space_percentage",
        "Current MQ errors file system free space percentage.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("DISK", "mq fdc file count"): _DescriptorMetricSpec(
        "ibmmq_qmgr_fdc_file_count",
        "Current number of MQ FDC files.",
    ),
    ("DISK", "mq trace file system bytes in use"): _DescriptorMetricSpec(
        "ibmmq_qmgr_trace_file_system_in_use_bytes",
        "Current MQ trace file system bytes in use.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "mq trace file system free space"): _DescriptorMetricSpec(
        "ibmmq_qmgr_trace_file_system_free_space_percentage",
        "Current MQ trace file system free space percentage.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("DISK", "queue manager file system bytes in use"): _DescriptorMetricSpec(
        "ibmmq_qmgr_file_system_in_use_bytes",
        "Current queue manager file system bytes in use.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "queue manager file system free space"): _DescriptorMetricSpec(
        "ibmmq_qmgr_file_system_free_space_percentage",
        "Current queue manager file system free space percentage.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("DISK", "log bytes in use"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_in_use_bytes",
        "Current log bytes in use.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "log bytes max"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_max_bytes",
        "Current maximum writable log bytes.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "log file system bytes in use"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_file_system_in_use_bytes",
        "Current log file system bytes in use.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "log file system bytes max"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_file_system_max_bytes",
        "Current log file system maximum bytes.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "log file system free space"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_file_system_free_space_percentage",
        "Current log file system free space percentage.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("DISK", "log disk written log sequence number"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_disk_written_lsn",
        "Current log sequence number written and forced to disk.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "log physical bytes written for the current interval"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_physical_bytes_written_total",
        "Interval total physical log bytes written during the published monitoring interval.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "log logical bytes written for the current interval"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_logical_bytes_written_total",
        "Interval total logical log bytes written during the published monitoring interval.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "log write latency"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_write_latency_seconds",
        "Rolling average log write latency in seconds.",
    ),
    ("DISK", "log write size"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_write_size_bytes",
        "Rolling average log write size in bytes.",
        ("MQIAMO64_BYTES",),
    ),
    ("DISK", "log current primary space in use"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_current_primary_space_in_use_percentage",
        "Current log primary space in use percentage.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("DISK", "log workload primary space utilization"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_workload_primary_space_utilization_percentage",
        "Rolling average log workload primary space utilization percentage.",
        ("MQIAMO_MONITOR_PERCENT",),
    ),
    ("DISK", "log slowest write since restart"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_slowest_write_seconds",
        "Slowest individual log write since restart, in seconds.",
    ),
    ("DISK", "log timestamp of slowest write"): _DescriptorMetricSpec(
        "ibmmq_qmgr_log_slowest_write_timestamp_seconds",
        "Unix timestamp of the slowest individual log write since restart, in seconds.",
    ),
}


@dataclass(frozen=True)
class MQCollectionError(RuntimeError):
    message: str
    completion_code: int | None = None
    reason_code: int | None = None
    reason_name: str | None = None
    operation: str | None = None
    object_type: str | None = None
    object_name: str | None = None

    def __str__(self) -> str:
        return self.message


class PyMQICollector:
    def __init__(self) -> None:
        try:
            import pymqi  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pymqi is required to collect MQ metrics") from exc
        self.pymqi = pymqi
        self._session_lock = RLock()
        self._sessions: dict[str, _CollectorSession] = {}
        self._selector_names = self._build_selector_name_map()

    def close(self) -> None:
        with self._session_lock:
            names = list(self._sessions)
        for name in names:
            self._invalidate_session(name)

    def collect(self, config: QueueManagerConfig) -> list[MetricRecord]:
        session = self._get_or_create_session(config)
        try:
            pcf = self.pymqi.PCFExecute(session.qmgr)
            records: list[MetricRecord] = []
            if config.metrics.include_queue_manager:
                records.extend(self._collect_qmgr_metrics(config, pcf))
            if config.metrics.include_queues:
                records.extend(self._collect_queue_metrics(config, pcf))
            if getattr(config.metrics, "include_topics", False):
                records.extend(self._collect_topic_metrics(config, pcf))
            if config.metrics.include_channels:
                records.extend(self._collect_channel_metrics(config, pcf))
            if config.metrics.include_accounting:
                records.extend(self._collect_accounting_metrics(config, session.qmgr))
            if getattr(config.metrics, "include_statistics", False):
                records.extend(self._collect_statistics_metrics(config, session.qmgr))
            if config.metrics.include_activity_trace:
                records.extend(self._collect_activity_trace_metrics(config, session.qmgr))
            if getattr(config.metrics, "include_system_topic_stream", False):
                records.extend(self._collect_system_topic_stream_metrics(config, session))
            return records
        except Exception:
            self._invalidate_session(config.name)
            raise

    def _get_or_create_session(self, config: QueueManagerConfig) -> _CollectorSession:
        with self._session_lock:
            session = self._sessions.get(config.name)
            if session is not None:
                return session

        qmgr = self._connect(config)
        subscriptions: list[Any] = []
        try:
            if getattr(config.metrics, "include_system_topic_stream", False):
                subscriptions = self._open_system_topic_subscriptions(config, qmgr)
        except Exception:
            try:
                qmgr.disconnect()
            except Exception:
                LOG.debug("Disconnect failed while tearing down partial session for %s", config.name, exc_info=True)
            raise

        session = _CollectorSession(qmgr=qmgr, subscriptions=subscriptions)
        with self._session_lock:
            self._sessions[config.name] = session
        return session

    def _invalidate_session(self, qmgr_name: str) -> None:
        with self._session_lock:
            session = self._sessions.pop(qmgr_name, None)
        if session is None:
            return

        for subscription in session.subscriptions:
            try:
                subscription.close(close_sub_queue=True)
            except Exception:
                LOG.debug("Subscription close failed for %s", qmgr_name, exc_info=True)

        try:
            session.qmgr.disconnect()
        except Exception:
            LOG.debug("Disconnect failed for %s", qmgr_name, exc_info=True)

    def _connect(self, config: QueueManagerConfig):
        password = config.connection.resolved_password()
        try:
            return self.pymqi.connect(
                config.connection.queue_manager,
                config.connection.channel,
                config.connection.conn_name,
                config.connection.user,
                password,
            )
        except self.pymqi.MQMIError as exc:
            raise self._build_mq_error(
                config,
                exc,
                operation="connect",
                object_type="queue manager",
                object_name=config.connection.queue_manager,
            ) from exc

    def _open_system_topic_subscriptions(self, config: QueueManagerConfig, qmgr) -> list[Any]:
        subscriptions: list[Any] = []
        sub_opts = (
            getattr(self.pymqi.CMQC, "MQSO_CREATE", 0)
            | getattr(self.pymqi.CMQC, "MQSO_NON_DURABLE", 0)
            | getattr(self.pymqi.CMQC, "MQSO_MANAGED", 0)
        )
        root_topic = getattr(config.metrics, "system_topic_root_topic", "SYSTEM.ADMIN.TOPIC")
        pcf = self.pymqi.PCFExecute(qmgr)
        root_topic_strings = self._resolve_topic_status_strings(
            config,
            pcf,
            root_topic,
            getattr(self.pymqi.CMQC, "MQCA_TOPIC_NAME", None),
            getattr(self.pymqi.CMQC, "MQCA_TOPIC_STRING", None),
        )

        for pattern in self._resolved_system_topic_patterns(config):
            kwargs: dict[str, Any] = {
                "sub_opts": sub_opts,
                "topic_string": self._resolve_subscription_topic_string(pattern, root_topic_strings),
            }

            try:
                subscription = self.pymqi.Subscription(qmgr)
                subscription.sub(**kwargs)
                if subscription.get_sub_queue() is None:
                    raise RuntimeError(f"Managed subscription queue was not created for topic pattern {pattern!r}")
                subscriptions.append(subscription)
            except self.pymqi.MQMIError as exc:
                raise self._build_mq_error(
                    config,
                    exc,
                    operation="open managed subscription",
                    object_type="topic",
                    object_name=pattern,
                ) from exc
            except Exception as exc:
                raise MQCollectionError(
                    f"IBM MQ operation open managed subscription failed for {config.name}; topic={pattern!r}; detail={exc}"
                ) from exc
        return subscriptions

    def _resolved_system_topic_patterns(self, config: QueueManagerConfig) -> tuple[str, ...]:
        resolved: list[str] = []
        for pattern in getattr(config.metrics, "system_topic_subscription_patterns", ()):
            resolved.append(
                pattern.format(
                    qmgr=config.name,
                    queue_manager=config.connection.queue_manager,
                )
            )
        return tuple(resolved)

    @staticmethod
    def _resolve_subscription_topic_string(pattern: str, root_topic_strings: tuple[str, ...]) -> str:
        if pattern.startswith("$SYS/"):
            return pattern
        if pattern.startswith("INFO/"):
            return f"$SYS/MQ/{pattern}"
        root = root_topic_strings[0] if root_topic_strings else ""
        if not root:
            raise MQCollectionError(
                f"IBM MQ managed subscription topic string could not be resolved for pattern {pattern!r}; use a full $SYS/MQ/... topic string."
            )
        return f"{root.rstrip('/')}/{pattern.lstrip('/')}"

    def _collect_qmgr_metrics(self, config: QueueManagerConfig, pcf) -> list[MetricRecord]:
        records: list[MetricRecord] = []
        responses = self._call_pcf(pcf.MQCMD_INQUIRE_Q_MGR, config, operation="MQCMD_INQUIRE_Q_MGR")
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
            responses = self._call_pcf(
                pcf.MQCMD_INQUIRE_Q,
                config,
                operation="MQCMD_INQUIRE_Q",
                object_type="queue",
                object_name=pattern,
                arguments={
                    queue_name_attr: pattern,
                    queue_type_attr: queue_type_local,
                },
            )
            for response in responses:
                queue_name = self._normalize_mq_string(response.get(queue_name_attr, ""))
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

    def _collect_topic_metrics(self, config: QueueManagerConfig, pcf) -> list[MetricRecord]:
        records: list[MetricRecord] = []
        topic_name_attr = getattr(self.pymqi.CMQC, "MQCA_TOPIC_NAME", None)
        topic_string_attr = getattr(self.pymqi.CMQC, "MQCA_TOPIC_STRING", None)
        topic_status_type_attr = getattr(self.pymqi.CMQCFC, "MQIACF_TOPIC_STATUS_TYPE", None)
        topic_status_value = self._cmqcfc_value("MQIACF_TOPIC_STATUS")
        admin_topic_name_attr = getattr(self.pymqi.CMQC, "MQCA_ADMIN_TOPIC_NAME", None)
        if topic_string_attr is None:
            return records

        for pattern in getattr(config.metrics, "topic_patterns", ()):
            topic_strings = self._resolve_topic_status_strings(config, pcf, pattern, topic_name_attr, topic_string_attr)
            for topic_string_value in topic_strings:
                arguments = {topic_string_attr: topic_string_value}
                if topic_status_type_attr is not None and topic_status_value is not None:
                    arguments[topic_status_type_attr] = topic_status_value
                responses = self._call_pcf(
                    pcf.MQCMD_INQUIRE_TOPIC_STATUS,
                    config,
                    operation="MQCMD_INQUIRE_TOPIC_STATUS",
                    object_type="topic",
                    object_name=topic_string_value,
                    arguments=arguments,
                )
                for response in responses:
                    topic_string = self._normalize_mq_string(response.get(topic_string_attr, ""))
                    if not topic_string:
                        continue
                    labels = {"qmgr": config.name, "topic": topic_string}
                    admin_topic_name = self._normalize_mq_string(response.get(admin_topic_name_attr, "")) if admin_topic_name_attr is not None else ""
                    if admin_topic_name:
                        labels["admin_topic_name"] = admin_topic_name
                    for attr_name, spec in TOPIC_STATUS_SPECS.items():
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
                                labels=labels,
                                value=value,
                            )
                        )
        return records

    def _resolve_topic_status_strings(self, config: QueueManagerConfig, pcf, pattern: str, topic_name_attr, topic_string_attr) -> tuple[str, ...]:
        if self._looks_like_topic_string(pattern):
            return (pattern,)
        if topic_name_attr is None or topic_string_attr is None:
            return (pattern,)

        topic_attrs_attr = self._cmqcfc_value("MQIACF_TOPIC_ATTRS")
        arguments: dict[Any, Any] = {topic_name_attr: pattern}
        if topic_attrs_attr is not None:
            arguments[topic_attrs_attr] = [topic_string_attr]
        responses = self._call_pcf(
            pcf.MQCMD_INQUIRE_TOPIC,
            config,
            operation="MQCMD_INQUIRE_TOPIC",
            object_type="topic",
            object_name=pattern,
            arguments=arguments,
        )
        resolved: list[str] = []
        for response in responses:
            topic_string = self._normalize_mq_string(response.get(topic_string_attr, ""))
            if topic_string:
                resolved.append(topic_string)
        if resolved:
            return tuple(resolved)
        return (pattern,)

    @staticmethod
    def _looks_like_topic_string(pattern: str) -> bool:
        return any(marker in pattern for marker in ("/", "#", "+")) or pattern.startswith("$")

    def _collect_channel_metrics(self, config: QueueManagerConfig, pcf) -> list[MetricRecord]:
        records: list[MetricRecord] = []
        channel_name_attr = getattr(self.pymqi.CMQCFC, "MQCACH_CHANNEL_NAME", None)
        if channel_name_attr is None:
            return records

        for pattern in config.metrics.channel_patterns:
            responses = self._call_pcf(
                pcf.MQCMD_INQUIRE_CHANNEL_STATUS,
                config,
                operation="MQCMD_INQUIRE_CHANNEL_STATUS",
                object_type="channel",
                object_name=pattern,
                arguments={channel_name_attr: pattern},
            )
            for response in responses:
                channel_name = self._normalize_mq_string(response.get(channel_name_attr, ""))
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

    def _collect_accounting_metrics(self, config: QueueManagerConfig, qmgr) -> list[MetricRecord]:
        return self._collect_admin_queue_metrics(
            config,
            qmgr,
            queue_name=config.metrics.accounting_queue_name,
            source_name="accounting",
            parser=self._parse_accounting_message,
        )

    def _collect_statistics_metrics(self, config: QueueManagerConfig, qmgr) -> list[MetricRecord]:
        return self._collect_admin_queue_metrics(
            config,
            qmgr,
            queue_name=getattr(config.metrics, "statistics_queue_name", "SYSTEM.ADMIN.STATISTICS.QUEUE"),
            source_name="statistics",
            parser=self._parse_statistics_message,
        )

    def _collect_activity_trace_metrics(self, config: QueueManagerConfig, qmgr) -> list[MetricRecord]:
        return self._collect_admin_queue_metrics(
            config,
            qmgr,
            queue_name=config.metrics.activity_trace_queue_name,
            source_name="activity_trace",
            parser=self._parse_activity_trace_message,
        )

    def _collect_system_topic_stream_metrics(self, config: QueueManagerConfig, session: _CollectorSession) -> list[MetricRecord]:
        records: list[MetricRecord] = []
        drained = 0
        max_messages = int(getattr(config.metrics, "system_topic_max_messages_per_poll", 500))
        topic_object = getattr(config.metrics, "system_topic_root_topic", "SYSTEM.ADMIN.TOPIC")

        for subscription in session.subscriptions:
            queue = subscription.get_sub_queue()
            if queue is None:
                raise MQCollectionError(
                    f"IBM MQ managed subscription queue was not available for {config.name}; topic_object={topic_object!r}"
                )
            for md, payload in self._drain_queue(queue, config, topic_object, max_messages=max_messages - drained):
                drained += 1
                records.extend(self._parse_system_topic_publication(config, md, payload))
                if drained >= max_messages:
                    break
            if drained >= max_messages:
                break

        records.append(
            MetricRecord(
                name=SYSTEM_TOPIC_STREAM_COUNT_SPEC.metric_name,
                documentation=SYSTEM_TOPIC_STREAM_COUNT_SPEC.help_text,
                labels={"qmgr": config.name, "topic_object": topic_object},
                value=float(drained),
            )
        )
        return records

    def _collect_admin_queue_metrics(self, config: QueueManagerConfig, qmgr, *, queue_name: str, source_name: str, parser) -> list[MetricRecord]:
        queue = None
        drained = 0
        records: list[MetricRecord] = []
        try:
            queue = self._open_input_queue(qmgr, config, queue_name)
            for md, payload in self._drain_queue(queue, config, queue_name):
                drained += 1
                records.extend(parser(config, queue_name, md, payload))
        finally:
            if queue is not None:
                try:
                    queue.close()
                except Exception:
                    LOG.debug("Close failed for %s on %s", queue_name, config.name, exc_info=True)

        records.append(
            MetricRecord(
                name=ADMIN_QUEUE_MESSAGE_SPECS[source_name].metric_name,
                documentation=ADMIN_QUEUE_MESSAGE_SPECS[source_name].help_text,
                labels={"qmgr": config.name, "queue": queue_name},
                value=float(drained),
            )
        )
        return records

    def _open_input_queue(self, qmgr, config: QueueManagerConfig, queue_name: str):
        options = (
            getattr(self.pymqi.CMQC, "MQOO_INPUT_SHARED", 0)
            | getattr(self.pymqi.CMQC, "MQOO_FAIL_IF_QUIESCING", 0)
        )
        try:
            return self.pymqi.Queue(qmgr, queue_name, options)
        except self.pymqi.MQMIError as exc:
            raise self._build_mq_error(
                config,
                exc,
                operation="open input queue",
                object_type="queue",
                object_name=queue_name,
            ) from exc

    def _drain_queue(
        self,
        queue,
        config: QueueManagerConfig,
        queue_name: str,
        *,
        max_messages: int | None = None,
    ) -> Iterable[tuple[Any, bytes]]:
        gmo = self.pymqi.GMO()
        gmo.Options = (
            getattr(self.pymqi.CMQC, "MQGMO_NO_WAIT", 0)
            | getattr(self.pymqi.CMQC, "MQGMO_FAIL_IF_QUIESCING", 0)
            | getattr(self.pymqi.CMQC, "MQGMO_CONVERT", 0)
        )
        drained = 0
        while True:
            if max_messages is not None and drained >= max_messages:
                return
            md = self.pymqi.MD()
            try:
                payload = queue.get(None, md, gmo)
            except self.pymqi.MQMIError as exc:
                if getattr(exc, "reason", None) == getattr(self.pymqi.CMQC, "MQRC_NO_MSG_AVAILABLE", 2033):
                    return
                raise self._build_mq_error(
                    config,
                    exc,
                    operation="drain queue",
                    object_type="queue",
                    object_name=queue_name,
                ) from exc
            drained += 1
            yield md, payload

    def _parse_accounting_message(self, config: QueueManagerConfig, queue_name: str, md, payload: bytes) -> list[MetricRecord]:
        unpacked = self._unpack_pcf_message(config, queue_name, payload, operation="parse accounting message")
        groups = self._find_group_dicts(unpacked, self._cmqcfc_value("MQGACF_Q_ACCOUNTING_DATA"))
        records: list[MetricRecord] = []
        for group in groups:
            labels = self._message_labels(config, queue_name, md, group)
            for attr_name, spec in ACCOUNTING_SPECS.items():
                attr_id = self._cmqcfc_value(attr_name)
                if attr_id is None or attr_id not in group:
                    continue
                value = self._coerce_numeric(group[attr_id])
                if value is None:
                    continue
                records.append(
                    MetricRecord(
                        name=spec.metric_name,
                        documentation=spec.help_text,
                        labels=labels,
                        value=value,
                    )
                )
        return records

    def _parse_statistics_message(self, config: QueueManagerConfig, queue_name: str, md, payload: bytes) -> list[MetricRecord]:
        unpacked = self._unpack_pcf_message(config, queue_name, payload, operation="parse statistics message")
        groups = self._find_group_dicts(unpacked, self._cmqcfc_value("MQGACF_Q_STATISTICS_DATA"))
        records: list[MetricRecord] = []
        for group in groups:
            labels = self._statistics_labels(config, queue_name, group)
            for attr_name, spec in STATISTICS_SPECS.items():
                attr_id = self._cmqcfc_value(attr_name)
                if attr_id is None or attr_id not in group:
                    continue
                value = self._coerce_numeric(group[attr_id])
                if value is None:
                    continue
                records.append(
                    MetricRecord(
                        name=spec.metric_name,
                        documentation=spec.help_text,
                        labels=labels,
                        value=value,
                    )
                )
        return records

    def _parse_activity_trace_message(self, config: QueueManagerConfig, queue_name: str, md, payload: bytes) -> list[MetricRecord]:
        unpacked = self._unpack_pcf_message(config, queue_name, payload, operation="parse activity trace message")
        activity_group_id = self._cmqcfc_value("MQGACF_ACTIVITY")
        groups = self._find_group_dicts(unpacked, activity_group_id)
        if not groups and isinstance(unpacked, dict):
            groups = [unpacked]
        records: list[MetricRecord] = []
        operation_type_id = self._cmqcfc_value("MQIACF_OPERATION_TYPE")
        operation_id_id = self._cmqcfc_value("MQIACF_OPERATION_ID")
        for group in groups:
            labels = self._message_labels(config, queue_name, md, group)
            if operation_type_id is not None and operation_type_id in group:
                labels["operation"] = self._operation_name(group[operation_type_id])
            if operation_id_id is not None and operation_id_id in group:
                labels["operation_id"] = str(group[operation_id_id])
            records.append(
                MetricRecord(
                    name=ACTIVITY_OPERATION_SPEC.metric_name,
                    documentation=ACTIVITY_OPERATION_SPEC.help_text,
                    labels=labels,
                    value=1.0,
                )
            )
        return records

    def _parse_system_topic_publication(self, config: QueueManagerConfig, md, payload: bytes) -> list[MetricRecord]:
        published_topic = "<unknown>"
        body = payload

        if self._is_rfh2_message(md, payload):
            try:
                rfh2 = self.pymqi.RFH2()
                rfh2.unpack(payload, getattr(md, "Encoding", None))
                published_topic = self._extract_rfh2_topic_string(rfh2) or published_topic
                body = payload[int(rfh2["StrucLength"]):]
            except Exception:
                LOG.debug("Failed to parse RFH2 header for system topic publication on %s", config.name, exc_info=True)

        topic_labels = self._system_topic_labels(config, published_topic)
        records = [
            MetricRecord(
                name=SYSTEM_TOPIC_PUBLICATION_COUNT_SPEC.metric_name,
                documentation=SYSTEM_TOPIC_PUBLICATION_COUNT_SPEC.help_text,
                labels=topic_labels,
                value=1.0,
            ),
            MetricRecord(
                name=SYSTEM_TOPIC_PUBLICATION_BYTES_SPEC.metric_name,
                documentation=SYSTEM_TOPIC_PUBLICATION_BYTES_SPEC.help_text,
                labels=topic_labels,
                value=float(len(payload)),
            ),
        ]

        if not body:
            return records

        try:
            unpacked, _cfh = self.pymqi.PCFExecute.unpack(body)
        except Exception:
            LOG.debug("System topic publication body was not decoded as PCF on %s", config.name, exc_info=True)
            records.extend(self._monitor_discovery_records(topic_labels))
            return records

        records.extend(self._system_topic_pcf_records(topic_labels, unpacked))
        records.extend(self._explicit_system_topic_records(topic_labels, unpacked))
        records.extend(self._normalized_system_topic_records(topic_labels, unpacked))
        return records

    def _unpack_pcf_message(self, config: QueueManagerConfig, queue_name: str, payload: bytes, *, operation: str) -> dict[Any, Any]:
        try:
            unpacked, _cfh = self.pymqi.PCFExecute.unpack(payload)
        except Exception as exc:
            raise MQCollectionError(
                message=(
                    f"IBM MQ operation {operation} failed for {config.name}; "
                    f"queue={queue_name!r}. Unable to decode PCF payload from the admin queue."
                ),
                operation=operation,
                object_type="queue",
                object_name=queue_name,
            ) from exc
        if not isinstance(unpacked, dict):
            raise MQCollectionError(
                message=(
                    f"IBM MQ operation {operation} failed for {config.name}; "
                    f"queue={queue_name!r}. PCF payload was not decoded into a dictionary."
                ),
                operation=operation,
                object_type="queue",
                object_name=queue_name,
            )
        return unpacked

    def _find_group_dicts(self, data: Any, group_id: int | None) -> list[dict[Any, Any]]:
        matches: list[dict[Any, Any]] = []
        if isinstance(data, dict):
            if group_id is not None:
                group_value = data.get(group_id)
                if isinstance(group_value, list):
                    for item in group_value:
                        if isinstance(item, dict):
                            matches.append(item)
            for value in data.values():
                matches.extend(self._find_group_dicts(value, group_id))
        elif isinstance(data, list):
            for item in data:
                matches.extend(self._find_group_dicts(item, group_id))
        return matches

    def _message_labels(self, config: QueueManagerConfig, queue_name: str, md, group: dict[Any, Any]) -> dict[str, str]:
        appl_name = self._first_string(
            group.get(self._cmqcfc_value("MQCACF_APPL_NAME")),
            group.get(self._cmqcfc_value("MQCACF_EVENT_APPL_NAME")),
            getattr(md, "PutApplName", b""),
        )
        object_name = self._first_string(
            group.get(self._cmqcfc_value("MQCACF_OBJECT_NAME")),
            group.get(self._cmqcfc_value("MQCACF_RESOLVED_Q_NAME")),
            group.get(self._cmqcfc_value("MQCACF_TO_Q_NAME")),
            group.get(self._cmqcfc_value("MQCACF_FROM_Q_NAME")),
            group.get(self._cmqcfc_value("MQCACF_OBJECT_STRING")),
            group.get(self._cmqcfc_value("MQCACF_RESOLVED_OBJECT_STRING")),
            group.get(self._cmqcfc_value("MQCACF_TOPIC")),
            group.get(self._cmqcfc_value("MQCACF_TO_TOPIC_NAME")),
            group.get(self._cmqcfc_value("MQCACF_FROM_TOPIC_NAME")),
        )
        object_type = self._object_type_name(group.get(self._cmqcfc_value("MQIACF_OBJECT_TYPE")))
        return {
            "qmgr": config.name,
            "queue": queue_name,
            "appl_name": appl_name or "<unknown>",
            "object_name": object_name or "<unknown>",
            "object_type": object_type,
        }

    def _statistics_labels(self, config: QueueManagerConfig, queue_name: str, group: dict[Any, Any]) -> dict[str, str]:
        object_name = self._first_string(
            group.get(self._cmqcfc_value("MQCACF_OBJECT_NAME")),
            group.get(self._cmqcfc_value("MQCACF_RESOLVED_Q_NAME")),
            group.get(self._cmqcfc_value("MQCACF_Q_NAME")),
        )
        return {
            "qmgr": config.name,
            "queue": queue_name,
            "object_name": object_name or "<unknown>",
            "object_type": self._object_type_name(group.get(self._cmqcfc_value("MQIACF_OBJECT_TYPE"))),
        }

    def _system_topic_labels(self, config: QueueManagerConfig, published_topic: str) -> dict[str, str]:
        monitor_path = self._parse_monitor_path(published_topic)
        return {
            "qmgr": config.name,
            "published_topic": published_topic,
            "monitor_class": monitor_path["monitor_class"],
            "monitor_branch": monitor_path["monitor_branch"],
            "monitor_leaf": monitor_path["monitor_leaf"],
        }

    def _system_topic_pcf_records(self, topic_labels: dict[str, str], data: Any, *, context: str = "root") -> list[MetricRecord]:
        records: list[MetricRecord] = []
        if isinstance(data, dict):
            base_labels = dict(topic_labels)
            base_labels["pcf_context"] = context
            base_labels["object_name"] = self._first_string(
                data.get(self._cmqcfc_value("MQCACF_OBJECT_NAME")),
                data.get(self._cmqcfc_value("MQCACF_Q_NAME")),
                data.get(self._cmqcfc_value("MQCACF_RESOLVED_Q_NAME")),
                data.get(self._cmqcfc_value("MQCACF_TOPIC")),
            ) or "<none>"
            base_labels["object_type"] = self._object_type_name(data.get(self._cmqcfc_value("MQIACF_OBJECT_TYPE")))
            base_labels["appl_name"] = self._first_string(data.get(self._cmqcfc_value("MQCACF_APPL_NAME"))) or "<none>"

            for key, value in data.items():
                selector_name = self._selector_name(key)
                numeric_value = self._coerce_numeric(value)
                if selector_name and numeric_value is not None:
                    records.append(
                        MetricRecord(
                            name=f"ibmmq_system_topic_{selector_name.lower()}",
                            documentation=f"IBM MQ system topic PCF attribute {selector_name} observed on the managed subscription stream.",
                            labels=base_labels,
                            value=numeric_value,
                        )
                    )
                next_context = selector_name or context
                if isinstance(value, (dict, list)):
                    records.extend(self._system_topic_pcf_records(topic_labels, value, context=next_context))
        elif isinstance(data, list):
            for item in data:
                records.extend(self._system_topic_pcf_records(topic_labels, item, context=context))
        return records

    def _normalized_system_topic_records(self, topic_labels: dict[str, str], data: Any) -> list[MetricRecord]:
        monitor_class = topic_labels.get("monitor_class", "<unknown>")
        if monitor_class not in _SYSTEM_TOPIC_KNOWN_CLASSES:
            return self._monitor_discovery_records(topic_labels)
        return self._normalized_system_topic_records_inner(topic_labels, data)

    def _explicit_system_topic_records(self, topic_labels: dict[str, str], data: Any) -> list[MetricRecord]:
        monitor_class = topic_labels.get("monitor_class", "<unknown>")
        if monitor_class not in _SYSTEM_TOPIC_KNOWN_CLASSES:
            return []
        return self._explicit_system_topic_records_inner(topic_labels, data)

    def _explicit_system_topic_records_inner(self, topic_labels: dict[str, str], data: Any, *, context: str = "root") -> list[MetricRecord]:
        records: list[MetricRecord] = []
        if isinstance(data, dict):
            labels = self._system_topic_metric_labels(topic_labels, data, context)
            monitor_class = topic_labels["monitor_class"]
            descriptor_spec, descriptor_value = self._descriptor_metric_match(monitor_class, labels.get("monitor_desc", "<none>"), data)
            if descriptor_spec is not None and descriptor_value is not None:
                records.append(
                    MetricRecord(
                        name=descriptor_spec.metric_name,
                        documentation=descriptor_spec.help_text,
                        labels=labels,
                        value=self._scale_descriptor_system_topic_value(descriptor_spec.metric_name, descriptor_value),
                    )
                )
            for key, value in data.items():
                selector_name = self._selector_name(key)
                numeric_value = self._coerce_numeric(value)
                spec = _EXPLICIT_SYSTEM_TOPIC_METRICS.get((monitor_class, selector_name or ""))
                if spec is not None and numeric_value is not None:
                    records.append(
                        MetricRecord(
                            name=spec.metric_name,
                            documentation=spec.help_text,
                            labels=labels,
                            value=self._scale_explicit_system_topic_value(selector_name, numeric_value),
                        )
                    )
                next_context = selector_name or context
                if isinstance(value, (dict, list)):
                    records.extend(self._explicit_system_topic_records_inner(topic_labels, value, context=next_context))
        elif isinstance(data, list):
            for item in data:
                records.extend(self._explicit_system_topic_records_inner(topic_labels, item, context=context))
        return records

    def _normalized_system_topic_records_inner(self, topic_labels: dict[str, str], data: Any, *, context: str = "root") -> list[MetricRecord]:
        records: list[MetricRecord] = []
        if isinstance(data, dict):
            labels = self._system_topic_metric_labels(topic_labels, data, context)
            metric_prefix = topic_labels["monitor_class"].lower()
            for key, value in data.items():
                selector_name = self._selector_name(key)
                numeric_value = self._coerce_numeric(value)
                clean_name = self._clean_selector_name(selector_name)
                if clean_name and numeric_value is not None:
                    records.append(
                        MetricRecord(
                            name=f"ibmmq_{metric_prefix}_{clean_name}",
                            documentation=f"IBM MQ {topic_labels['monitor_class']} system-topic metric derived from selector {selector_name}.",
                            labels=labels,
                            value=numeric_value,
                        )
                    )
                next_context = selector_name or context
                if isinstance(value, (dict, list)):
                    records.extend(self._normalized_system_topic_records_inner(topic_labels, value, context=next_context))
        elif isinstance(data, list):
            for item in data:
                records.extend(self._normalized_system_topic_records_inner(topic_labels, item, context=context))
        return records

    def _system_topic_metric_labels(self, topic_labels: dict[str, str], data: dict[Any, Any], context: str) -> dict[str, str]:
        return {
            "qmgr": topic_labels["qmgr"],
            "monitor_branch": topic_labels.get("monitor_branch", "<unknown>"),
            "monitor_leaf": topic_labels.get("monitor_leaf", "<none>"),
            "pcf_context": context,
            "object_name": self._first_string(
                data.get(self._cmqcfc_value("MQCACF_OBJECT_NAME")),
                data.get(self._cmqcfc_value("MQCACF_Q_NAME")),
                data.get(self._cmqcfc_value("MQCACF_RESOLVED_Q_NAME")),
                data.get(self._cmqcfc_value("MQCACF_TOPIC")),
            ) or "<none>",
            "object_type": self._object_type_name(data.get(self._cmqcfc_value("MQIACF_OBJECT_TYPE"))),
            "appl_name": self._first_string(data.get(self._cmqcfc_value("MQCACF_APPL_NAME"))) or "<none>",
            "monitor_desc": self._first_string(data.get(self._cmqcfc_value("MQCAMO_MONITOR_DESC"))) or "<none>",
            "monitor_type_desc": self._first_string(data.get(self._cmqcfc_value("MQCAMO_MONITOR_TYPE"))) or "<none>",
        }

    def _descriptor_metric_match(
        self,
        monitor_class: str,
        monitor_desc: str,
        data: dict[Any, Any],
    ) -> tuple[_DescriptorMetricSpec | None, float | None]:
        desc_key = self._normalize_monitor_descriptor(monitor_desc)
        spec = _DESCRIPTOR_SYSTEM_TOPIC_METRICS.get((monitor_class, desc_key))
        if spec is None:
            return None, None
        if spec.preferred_selectors:
            for selector_name in spec.preferred_selectors:
                selector_value = self._selector_value_by_name(data, selector_name)
                if selector_value is not None:
                    return spec, selector_value
        return spec, self._first_non_metadata_numeric_value(data)

    def _selector_value_by_name(self, data: dict[Any, Any], selector_name: str) -> float | None:
        for key, value in data.items():
            if self._selector_name(key) != selector_name:
                continue
            return self._coerce_numeric(value)
        return None

    def _first_non_metadata_numeric_value(self, data: dict[Any, Any]) -> float | None:
        for key, value in data.items():
            selector_name = self._selector_name(key)
            if selector_name in _SYSTEM_TOPIC_METADATA_SELECTORS:
                continue
            if selector_name and selector_name.startswith("MQCACF_"):
                continue
            numeric_value = self._coerce_numeric(value)
            if numeric_value is not None:
                return numeric_value
        return None

    @staticmethod
    def _scale_explicit_system_topic_value(selector_name: str | None, numeric_value: float) -> float:
        if selector_name in _MICROSECOND_SELECTORS:
            return numeric_value / 1_000_000.0
        return numeric_value

    @staticmethod
    def _scale_descriptor_system_topic_value(metric_name: str, numeric_value: float) -> float:
        if metric_name.endswith("_seconds") or metric_name.endswith("_timestamp_seconds"):
            return numeric_value / 1_000_000.0
        return numeric_value

    @staticmethod
    def _normalize_monitor_descriptor(monitor_desc: str) -> str:
        pieces: list[str] = []
        current: list[str] = []
        for char in monitor_desc.lower():
            if char.isalnum():
                current.append(char)
                continue
            if current:
                pieces.append("".join(current))
                current = []
        if current:
            pieces.append("".join(current))
        return " ".join(pieces)

    def _monitor_discovery_records(self, topic_labels: dict[str, str]) -> list[MetricRecord]:
        discovery_labels = {
            "qmgr": topic_labels["qmgr"],
            "published_topic": topic_labels["published_topic"],
            "monitor_class": topic_labels.get("monitor_class", "<unknown>"),
            "monitor_branch": topic_labels.get("monitor_branch", "<unknown>"),
            "monitor_leaf": topic_labels.get("monitor_leaf", "<none>"),
        }
        return [
            MetricRecord(
                name="ibmmq_monitor_discovery_publications",
                documentation="System-topic discovery or unclassified monitoring publications observed during the last poll.",
                labels=discovery_labels,
                value=1.0,
            )
        ]

    @staticmethod
    def _parse_monitor_path(published_topic: str) -> dict[str, str]:
        monitor_class = "<unknown>"
        monitor_branch = "<unknown>"
        monitor_leaf = "<none>"
        marker = "/Monitor/"
        if marker in published_topic:
            suffix = published_topic.split(marker, 1)[1]
            pieces = [piece for piece in suffix.split("/") if piece]
            if pieces:
                monitor_class = pieces[0]
            if len(pieces) > 1:
                monitor_branch = pieces[1]
            if len(pieces) > 2:
                monitor_leaf = "/".join(pieces[2:])
            elif len(pieces) == 2:
                monitor_leaf = "<none>"
        return {
            "monitor_class": monitor_class,
            "monitor_branch": monitor_branch,
            "monitor_leaf": monitor_leaf,
        }

    def _build_selector_name_map(self) -> dict[int, str]:
        selector_names: dict[int, str] = {}
        for namespace in (getattr(self.pymqi, "CMQC", None), getattr(self.pymqi, "CMQCFC", None)):
            if namespace is None:
                continue
            for attr_name in dir(namespace):
                if not attr_name.startswith("MQ"):
                    continue
                value = getattr(namespace, attr_name, None)
                if isinstance(value, int):
                    selector_names.setdefault(value, attr_name)
        return selector_names

    def _selector_name(self, selector: Any) -> str | None:
        if isinstance(selector, int):
            return self._selector_names.get(selector)
        return None

    @staticmethod
    def _clean_selector_name(selector_name: str | None) -> str | None:
        if not selector_name:
            return None
        cleaned = selector_name
        for prefix in _SYSTEM_TOPIC_SELECTOR_PREFIXES:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
                break
        return cleaned.lower()

    def _extract_rfh2_topic_string(self, rfh2) -> str:
        folder = rfh2["mqps"] if "mqps" in rfh2.get() else None
        if not isinstance(folder, (bytes, bytearray)):
            return ""
        root = ElementTree.fromstring(bytes(folder).rstrip())
        top = root.find("Top")
        return top.text.strip() if top is not None and top.text else ""

    def _is_rfh2_message(self, md, payload: bytes) -> bool:
        message_format = getattr(md, "Format", b"")
        rfh2_format = getattr(self.pymqi.CMQC, "MQFMT_RF_HEADER_2", b"")
        rfh2_struct_id = getattr(self.pymqi.CMQC, "MQRFH_STRUC_ID", b"RFH ")
        return message_format == rfh2_format or payload.startswith(rfh2_struct_id)

    def _cmqcfc_value(self, attr_name: str) -> int | None:
        return getattr(self.pymqi.CMQCFC, attr_name, None)

    def _object_type_name(self, value: Any) -> str:
        if isinstance(value, int):
            for attr_name in dir(self.pymqi.CMQC):
                if not attr_name.startswith("MQOT_"):
                    continue
                if getattr(self.pymqi.CMQC, attr_name, None) == value:
                    return attr_name
            return str(value)
        return "<unknown>"

    def _operation_name(self, value: Any) -> str:
        if isinstance(value, int):
            for attr_name in dir(self.pymqi.CMQCFC):
                if not attr_name.startswith("MQOPER_"):
                    continue
                if getattr(self.pymqi.CMQCFC, attr_name, None) == value:
                    return attr_name
            return str(value)
        return "<unknown>"

    @staticmethod
    def _first_string(*values: Any) -> str:
        for value in values:
            text = PyMQICollector._normalize_mq_string(value)
            if text:
                return text
        return ""

    @staticmethod
    def _coerce_numeric(value: Any) -> float | None:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, (list, tuple)):
            total = 0.0
            saw_numeric = False
            for item in value:
                numeric = PyMQICollector._coerce_numeric(item)
                if numeric is None:
                    continue
                total += numeric
                saw_numeric = True
            if saw_numeric:
                return total
        return None

    @staticmethod
    def _normalize_mq_string(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore").strip(" \x00")
        if isinstance(value, str):
            return value.strip(" \x00")
        return ""

    def _call_pcf(
        self,
        method,
        config: QueueManagerConfig,
        *,
        operation: str,
        object_type: str | None = None,
        object_name: str | None = None,
        arguments: dict[Any, Any] | None = None,
    ):
        try:
            if arguments is None:
                return method()
            return method(arguments)
        except self.pymqi.MQMIError as exc:
            raise self._build_mq_error(
                config,
                exc,
                operation=operation,
                object_type=object_type,
                object_name=object_name,
            ) from exc

    def _build_mq_error(
        self,
        config: QueueManagerConfig,
        exc: Exception,
        *,
        operation: str,
        object_type: str | None = None,
        object_name: str | None = None,
    ) -> MQCollectionError:
        completion_code = self._extract_error_code(exc, "comp")
        reason_code = self._extract_error_code(exc, "reason")
        reason_name = self._mq_reason_name(reason_code)
        message_parts = [f"IBM MQ operation {operation} failed for {config.name}"]
        if object_type and object_name:
            message_parts.append(f"{object_type}={object_name!r}")
        elif object_type:
            message_parts.append(f"object_type={object_type}")
        if completion_code is not None:
            message_parts.append(f"completion_code={completion_code}")
        if reason_code is not None:
            if reason_name:
                message_parts.append(f"reason={reason_code} ({reason_name})")
            else:
                message_parts.append(f"reason={reason_code}")
        detail = "; ".join(message_parts) + "."
        if reason_code == 2085 and object_type and object_name:
            detail += f" The requested {object_type} name {object_name!r} is unknown to the queue manager."
        return MQCollectionError(
            message=detail,
            completion_code=completion_code,
            reason_code=reason_code,
            reason_name=reason_name,
            operation=operation,
            object_type=object_type,
            object_name=object_name,
        )

    @staticmethod
    def _extract_error_code(exc: Exception, attribute: str) -> int | None:
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
        return None

    def _mq_reason_name(self, reason_code: int | None) -> str | None:
        if reason_code is None:
            return None
        for attr_name in dir(self.pymqi.CMQC):
            if not attr_name.startswith("MQRC_"):
                continue
            if getattr(self.pymqi.CMQC, attr_name, None) == reason_code:
                return attr_name
        return None
