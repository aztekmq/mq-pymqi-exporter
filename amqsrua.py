#!/usr/bin/env python3
"""
mq_srua_pymqi.py

Python 3 + PyMQI version of the core IBM MQ AMQSRUAA idea.

It subscribes to IBM MQ resource-usage topics under:

    $SYS/MQ/INFO/QMGR/<QMGR>/Monitor/...

Examples:

    python mq_srua_pymqi.py -m QM1 -c CPU -t QMgrSummary -n 5

    python mq_srua_pymqi.py -m QM1 -c CPU -t SystemSummary -n 5

    python mq_srua_pymqi.py -m QM1 -c STATQ -o APP.REQUEST -t PUT -n 5

    python mq_srua_pymqi.py -m QM1 -c STATQ -o APP.REQUEST -t GET -n 5

Client mode example:

    python mq_srua_pymqi.py ^
      -m QM1 ^
      --host localhost ^
      --port 1414 ^
      --channel DEV.APP.SVRCONN ^
      --user app ^
      --password passw0rd ^
      -c CPU ^
      -t QMgrSummary ^
      -n 5
"""

import argparse
import os
import struct
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pymqi
from pymqi import CMQC, CMQCFC


DEFAULT_PREFIX = "$SYS/MQ"
DEFAULT_WAIT_MS = 30000


@dataclass
class PCFParameter:
    pcf_type: int
    parameter: int
    value: Any


def mqstr(raw: bytes) -> str:
    """Decode MQ padded strings."""
    return raw.decode("utf-8", errors="replace").rstrip(" \x00")


def structural_field_name(parameter_id: int) -> Optional[str]:
    """Return a safe name for structural/non-metric PCF fields."""
    structural = {
        getattr(CMQCFC, "MQIAMO_MONITOR_CLASS", -999999): "monitor_class_id",
        getattr(CMQCFC, "MQIAMO_MONITOR_TYPE", -999999): "monitor_type_id",
        getattr(CMQCFC, "MQIAMO64_MONITOR_INTERVAL", -999999): "monitor_interval_microseconds",
        getattr(CMQC, "MQCA_Q_MGR_NAME", -999999): "queue_manager_name",
        getattr(CMQC, "MQCA_Q_NAME", -999999): "queue_name",
        getattr(CMQCFC, "MQCACF_APPL_NAME", -999999): "application_name",
        getattr(CMQCFC, "MQCACF_NHA_INSTANCE_NAME", -999999): "nha_instance_name",
    }
    return structural.get(parameter_id)


def resource_field_name(parameter_id: int) -> str:
    """Backward-compatible safe field name used for unknown elements."""
    return structural_field_name(parameter_id) or f"element_{parameter_id}"


# Built-in labels for the most common AMQSRUA resource usage topics.
# The full IBM C sample discovers these dynamically from the METADATA topics.
# This map gives you clean output immediately for the CPU and DISK examples.
# Values used for kind:
#   raw                 print as-is
#   mb                  append MB
#   bytes               append bytes
#   microseconds        append uSec
#   percent_hundredths  value is hundredths of a percent, e.g. 242 -> 2.42%
#   hundredths          value is hundredths, e.g. 800 -> 8.00
#   delta_bytes_rate    print byte delta plus bytes/sec using monitor interval
RESOURCE_ELEMENT_MAP = {
    ("CPU", "QMGRSUMMARY"): {
        0: ("User CPU time - percentage estimate for queue manager", "percent_hundredths"),
        1: ("System CPU time - percentage estimate for queue manager", "percent_hundredths"),
        2: ("RAM total bytes - estimate for queue manager", "mb"),
    },
    ("CPU", "SYSTEMSUMMARY"): {
        0: ("User CPU time percentage", "percent_hundredths"),
        1: ("System CPU time percentage", "percent_hundredths"),
        2: ("CPU load - one minute average", "hundredths"),
        3: ("CPU load - five minute average", "hundredths"),
        4: ("CPU load - fifteen minute average", "hundredths"),
        5: ("RAM free percentage", "percent_hundredths"),
        6: ("RAM total bytes", "mb"),
    },
    ("DISK", "LOG"): {
        0: ("Log - bytes in use", "bytes"),
        1: ("Log - bytes max", "bytes"),
        2: ("Log file system - bytes in use", "bytes"),
        3: ("Log file system - bytes max", "bytes"),
        4: ("Log - physical bytes written", "delta_bytes_rate"),
        5: ("Log - logical bytes written", "delta_bytes_rate"),
        6: ("Log - write latency", "microseconds"),
        7: ("Log - current primary space in use", "percent_hundredths"),
        8: ("Log - workload primary space utilization", "percent_hundredths"),
        12: ("Log - write size", "bytes"),
    },
}


def metric_definition(requested_class: str, requested_type: str, parameter_id: int):
    key = (requested_class.upper(), requested_type.upper())
    return RESOURCE_ELEMENT_MAP.get(key, {}).get(parameter_id)


def format_metric_value(value: Any, kind: str, interval_microseconds: Optional[int]) -> str:
    try:
        ivalue = int(value)
    except Exception:
        return str(value)

    if kind == "percent_hundredths":
        return f"{ivalue / 100:.2f}%"

    if kind == "hundredths":
        return f"{ivalue / 100:.2f}"

    if kind == "mb":
        return f"{ivalue} MB"

    if kind == "bytes":
        return f"{ivalue} bytes"

    if kind == "microseconds":
        return f"{ivalue} uSec"

    if kind == "delta_bytes_rate":
        if interval_microseconds and interval_microseconds >= 10000:
            rate = int((ivalue * 1_000_000 + (interval_microseconds / 2)) // interval_microseconds)
            return f"{ivalue} bytes  {rate}/sec"
        return f"{ivalue} bytes"

    return str(value)


def align4(n: int) -> int:
    return (n + 3) & ~3


def parse_pcf_message(data: bytes) -> List[PCFParameter]:
    """
    Minimal PCF parser for common resource-usage publications.

    Handles:
      MQCFH
      MQCFIN
      MQCFIN64
      MQCFST
      MQCFGR, recursively enough to flatten child parameters

    This is intentionally practical rather than a full PCF framework.
    """
    params: List[PCFParameter] = []

    if len(data) < 36:
        raise ValueError("Message too short to be a PCF message")

    # MQCFH is normally:
    # Type, StrucLength, Version, Command, MsgSeqNumber, Control,
    # CompCode, Reason, ParameterCount
    cfh = struct.unpack_from(">9i", data, 0)

    # Try native little-endian if big-endian looks wrong.
    if cfh[1] not in (36,):
        cfh = struct.unpack_from("<9i", data, 0)
        endian = "<"
    else:
        endian = ">"

    _cfh_type, cfh_len, _version, command, _seq, _control, comp, reason, parm_count = cfh

    offset = cfh_len

    def parse_one(off: int, depth: int = 0) -> int:
        if off + 8 > len(data):
            return len(data)

        pcf_type, struc_len = struct.unpack_from(f"{endian}2i", data, off)

        if struc_len <= 0:
            return len(data)

        # MQCFIN: Type, StrucLength, Parameter, Value
        if pcf_type == CMQCFC.MQCFT_INTEGER:
            _typ, slen, parm, value = struct.unpack_from(f"{endian}4i", data, off)
            params.append(PCFParameter(pcf_type, parm, value))
            return off + slen

        # MQCFIN64: Type, StrucLength, Parameter, Reserved, Value
        if pcf_type == CMQCFC.MQCFT_INTEGER64:
            # Layout has a reserved MQLONG before the 64-bit value.
            _typ, slen, parm, _reserved = struct.unpack_from(f"{endian}4i", data, off)
            value = struct.unpack_from(f"{endian}q", data, off + 16)[0]
            params.append(PCFParameter(pcf_type, parm, value))
            return off + slen

        # MQCFST:
        # Type, StrucLength, Parameter, CodedCharSetId, StringLength, String
        if pcf_type == CMQCFC.MQCFT_STRING:
            _typ, slen, parm, ccsid, strlen = struct.unpack_from(f"{endian}5i", data, off)
            start = off + 20
            raw = data[start:start + strlen]
            params.append(PCFParameter(pcf_type, parm, mqstr(raw)))
            return off + slen

        # MQCFGR:
        # Type, StrucLength, Parameter, ParameterCount, then child parameters.
        if pcf_type == CMQCFC.MQCFT_GROUP:
            _typ, slen, parm, child_count = struct.unpack_from(f"{endian}4i", data, off)
            params.append(PCFParameter(pcf_type, parm, f"GROUP({child_count})"))

            child_off = off + 16
            for _ in range(child_count):
                child_off = parse_one(child_off, depth + 1)

            return off + slen

        # Unknown PCF structure; skip it.
        return off + struc_len

    for _ in range(max(parm_count, 0)):
        if offset >= len(data):
            break
        offset = parse_one(offset)

    return params


def print_pcf_response(raw_message: bytes, requested_class: str, requested_type: str, md: Optional[pymqi.MD] = None) -> None:
    """
    Format MQ resource-usage publications with readable names where known.

    Structural fields are printed first. Resource elements are mapped by
    requested class/type. Unknown elements are still printed honestly as
    element_<id> so you can add new metadata mappings later.
    """
    try:
        params = parse_pcf_message(raw_message)
    except Exception as exc:
        print("Could not parse message as PCF.")
        print(f"Parse error: {exc}")
        print(f"Raw message length: {len(raw_message)} bytes")
        return

    interval_microseconds: Optional[int] = None
    structural_rows = []
    metric_rows = []

    for p in params:
        if p.pcf_type == CMQCFC.MQCFT_GROUP:
            continue

        structural_name = structural_field_name(p.parameter)
        if structural_name:
            if structural_name == "monitor_interval_microseconds":
                try:
                    interval_microseconds = int(p.value)
                    seconds = interval_microseconds / 1_000_000
                    structural_rows.append((structural_name, f"{p.value}  ({seconds:.3f} seconds)"))
                except Exception:
                    structural_rows.append((structural_name, str(p.value)))
            else:
                structural_rows.append((structural_name, str(p.value)))
            continue

        metric_def = metric_definition(requested_class, requested_type, p.parameter)
        if metric_def:
            metric_name, kind = metric_def
            metric_rows.append((metric_name, format_metric_value(p.value, kind, interval_microseconds)))
        else:
            metric_rows.append((f"element_{p.parameter}", str(p.value)))

    print("=" * 80)
    print("IBM MQ resource usage publication")

    if md is not None:
        try:
            put_date = md["PutDate"].decode() if isinstance(md["PutDate"], bytes) else md["PutDate"]
            put_time = md["PutTime"].decode() if isinstance(md["PutTime"], bytes) else md["PutTime"]
            print(f"PutDate: {put_date}  PutTime: {put_time}")
        except Exception:
            pass

    print(f"Requested class : {requested_class}")
    print(f"Requested type  : {requested_type}")
    print("-" * 80)

    for name, value in structural_rows:
        print(f"{name:<55} {value}")

    if metric_rows:
        print("-" * 80)
        for name, value in metric_rows:
            print(f"{name:<55} {value}")

    print()


def build_resource_topic(prefix: str, qmgr_name: str, class_name: str, type_name: str, object_name: Optional[str]) -> str:
    """
    Build common AMQSRUAA-style direct resource topic.

    Common forms:

      $SYS/MQ/INFO/QMGR/QM1/Monitor/CPU/QMgrSummary
      $SYS/MQ/INFO/QMGR/QM1/Monitor/CPU/SystemSummary
      $SYS/MQ/INFO/QMGR/QM1/Monitor/STATQ/APP.REQUEST/PUT
      $SYS/MQ/INFO/QMGR/QM1/Monitor/STATQ/APP.REQUEST/GET

    Note:
      The full IBM sample discovers the exact topic strings dynamically from metadata.
      This function implements the practical common topic convention.
    """
    prefix = prefix.rstrip("/")

    if object_name:
        return f"{prefix}/INFO/QMGR/{qmgr_name}/Monitor/{class_name}/{object_name}/{type_name}"

    return f"{prefix}/INFO/QMGR/{qmgr_name}/Monitor/{class_name}/{type_name}"


def connect_qmgr(args: argparse.Namespace) -> pymqi.QueueManager:
    """
    Connect either bindings mode or client mode.

    Bindings mode:
      python mq_srua_pymqi.py -m QM1 ...

    Client mode:
      python mq_srua_pymqi.py -m QM1 --host localhost --port 1414 --channel DEV.APP.SVRCONN ...
    """
    if args.host and args.channel:
        conn_info = f"{args.host}({args.port})"

        cd = pymqi.CD()
        cd.ChannelName = args.channel
        cd.ConnectionName = conn_info
        cd.ChannelType = CMQC.MQCHT_CLNTCONN
        cd.TransportType = CMQC.MQXPT_TCP

        sco = pymqi.SCO()

        qmgr = pymqi.QueueManager(None)

        if args.user:
            qmgr.connect_with_options(
                args.qmgr,
                cd=cd,
                sco=sco,
                user=args.user,
                password=args.password or "",
            )
        else:
            qmgr.connect_with_options(args.qmgr, cd=cd, sco=sco)

        return qmgr

    return pymqi.connect(args.qmgr)


def subscribe_and_get(
    qmgr: pymqi.QueueManager,
    topic_string: str,
    max_pubs: int,
    wait_ms: int,
    debug: int,
    requested_class: str,
    requested_type: str,
) -> None:
    """
    Subscribe non-durably to the requested topic and read publications.

    This uses a system-managed subscription object, which is simpler than
    manually opening SYSTEM.DEFAULT.MODEL.QUEUE.
    """
    if debug:
        print(f"Subscribing to topic: {topic_string}")

    sub_desc = pymqi.SD()
    sub_desc["Options"] = (
        CMQC.MQSO_CREATE
        + CMQC.MQSO_NON_DURABLE
        + CMQC.MQSO_MANAGED
        + CMQC.MQSO_FAIL_IF_QUIESCING
    )
    sub_desc["SubLevel"] = 9
    sub_desc.set_vs("ObjectString", topic_string)

    sub = pymqi.Subscription(qmgr)
    sub.sub(sub_desc=sub_desc)

    gmo = pymqi.GMO()
    gmo["Options"] = (
        CMQC.MQGMO_WAIT
        + CMQC.MQGMO_NO_SYNCPOINT
        + CMQC.MQGMO_CONVERT
        + CMQC.MQGMO_FAIL_IF_QUIESCING
        + CMQC.MQGMO_NO_PROPERTIES
    )
    gmo["WaitInterval"] = wait_ms
    gmo["MatchOptions"] = CMQC.MQMO_NONE

    count = 0

    while max_pubs < 0 or count < max_pubs:
        md = pymqi.MD()
        md["Encoding"] = CMQC.MQENC_NATIVE
        md["CodedCharSetId"] = CMQC.MQCCSI_Q_MGR

        try:
            data = sub.get(None, md, gmo)
        except pymqi.MQMIError as e:
            if e.reason == CMQC.MQRC_NO_MSG_AVAILABLE:
                print("No more messages available.")
                break

            print(f"MQGET failed: comp={e.comp} reason={e.reason}")
            raise

        count += 1

        if debug:
            print(f"Received publication #{count}, {len(data)} bytes")

        print_pcf_response(data, requested_class, requested_type, md)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Python 3 + PyMQI resource usage subscriber, inspired by IBM MQ amqsrua/amqsruaa."
    )

    parser.add_argument("-m", "--qmgr", required=True, help="Queue manager name")
    parser.add_argument("-c", "--class-name", required=True, help="Monitor class, for example CPU, STATQ, STATMQI, DISK")
    parser.add_argument("-t", "--type-name", required=True, help="Monitor type, for example QMgrSummary, SystemSummary, PUT, GET, Log")
    parser.add_argument("-o", "--object-name", help="Object name for object-qualified metrics, for example queue name for STATQ")
    parser.add_argument("-n", "--max-pubs", type=int, default=1, help="Number of publications to consume. Use -1 for unlimited.")
    parser.add_argument("-p", "--prefix", default=DEFAULT_PREFIX, help="Metadata/resource topic prefix. Default: $SYS/MQ")
    parser.add_argument("-d", "--debug", type=int, default=0, help="Debug level")
    parser.add_argument("--wait-ms", type=int, default=DEFAULT_WAIT_MS, help="MQGET wait interval in milliseconds")

    parser.add_argument("--host", help="Client connection host")
    parser.add_argument("--port", type=int, default=1414, help="Client connection port")
    parser.add_argument("--channel", help="Client SVRCONN channel")
    parser.add_argument("--user", help="Client user ID")
    parser.add_argument("--password", help="Client password")

    args = parser.parse_args()

    qmgr = None

    try:
        topic = build_resource_topic(
            prefix=args.prefix,
            qmgr_name=args.qmgr,
            class_name=args.class_name,
            type_name=args.type_name,
            object_name=args.object_name,
        )

        qmgr = connect_qmgr(args)
        subscribe_and_get(
            qmgr=qmgr,
            topic_string=topic,
            max_pubs=args.max_pubs,
            wait_ms=args.wait_ms,
            debug=args.debug,
            requested_class=args.class_name,
            requested_type=args.type_name,
        )

        return 0

    except pymqi.MQMIError as e:
        print(f"MQ error: comp={e.comp} reason={e.reason}", file=sys.stderr)
        return 20

    except KeyboardInterrupt:
        print("Interrupted.")
        return 130

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 20

    finally:
        if qmgr is not None:
            try:
                qmgr.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())