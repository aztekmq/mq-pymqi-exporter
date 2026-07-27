#!/usr/bin/env bash

set -Eeuo pipefail

VENV_PYTHON="/opt/mq-exporter-venv/bin/python"
EXPORTER_CONFIG="${EXPORTER_CONFIG:-/app/examples/exporter.yaml}"
EXPORTER_PORT="${EXPORTER_PORT:-9157}"

export MQ_INSTALLATION_PATH="/opt/mqm"
export LD_LIBRARY_PATH="/opt/mqm/lib64:/opt/mqm/lib:/opt/python311/lib:${LD_LIBRARY_PATH:-}"
export PATH="/opt/mq-exporter-venv/bin:/opt/python311/bin:/opt/mqm/bin:${PATH}"

log_info() {
    printf '[INFO] %s\n' "$*"
}

log_error() {
    printf '[ERROR] %s\n' "$*" >&2
}

[[ -f /opt/mqm/inc/cmqc.h ]] || {
    log_error "Missing IBM MQ header: /opt/mqm/inc/cmqc.h"
    exit 1
}

[[ -e /opt/mqm/lib64/libmqic_r.so ]] || {
    log_error "Missing IBM MQ library: /opt/mqm/lib64/libmqic_r.so"
    exit 1
}

[[ -x "${VENV_PYTHON}" ]] || {
    log_error "Missing exporter Python: ${VENV_PYTHON}"
    exit 1
}

[[ -f "${EXPORTER_CONFIG}" ]] || {
    log_error "Missing exporter config: ${EXPORTER_CONFIG}"
    exit 1
}

log_info "Runtime validation"
log_info "Python:"
"${VENV_PYTHON}" --version

log_info "pyMQI:"
"${VENV_PYTHON}" -c \
    'import pymqi; print(pymqi.__file__)'

log_info "Exporter:"
"${VENV_PYTHON}" -c \
    'import mq_exporter; print(mq_exporter.__file__)'

log_info "Starting mq-pymqi-exporter"
log_info "Configuration: ${EXPORTER_CONFIG}"
log_info "Endpoints:"
log_info "  http://localhost:${EXPORTER_PORT}/"
log_info "  http://localhost:${EXPORTER_PORT}/info"
log_info "  http://localhost:${EXPORTER_PORT}/status"
log_info "  http://localhost:${EXPORTER_PORT}/metrics"

exec "${VENV_PYTHON}" \
    -m mq_exporter.main \
    --config "${EXPORTER_CONFIG}"
