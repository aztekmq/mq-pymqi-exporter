#!/usr/bin/env bash
# =============================================================================
# Script Name : stop_pymqi_exporter.sh
# Description : Stop and remove the mq-pymqi-exporter Docker container.
#
# By default, this script:
#   - stops the exporter container
#   - removes the exporter container
#   - leaves Docker images, MQ containers, configuration files, and generated
#     build files intact
#
# Optional cleanup can also remove:
#   - the exporter image
#   - the generated Dockerfile and entrypoint
#   - the IBM MQ base image
#   - the Docker network, when unused
#
# Usage:
#
#   cd docker_build
#   chmod +x stop_pymqi_exporter.sh
#   ./stop_pymqi_exporter.sh
#
# Optional environment variables:
#
#   CONTAINER_NAME=mq-pymqi-exporter
#   EXPORTER_IMAGE=mq-pymqi-exporter:latest
#   BASE_IMAGE=mq-local-monitoring:latest
#   DOCKER_NETWORK=docker_build_default
#
#   REMOVE_CONTAINER=true
#   REMOVE_EXPORTER_IMAGE=false
#   REMOVE_BASE_IMAGE=false
#   REMOVE_GENERATED_FILES=false
#   REMOVE_NETWORK=false
#
# Examples:
#
#   Stop and remove only the exporter container:
#       ./stop_pymqi_exporter.sh
#
#   Also remove the exporter image:
#       REMOVE_EXPORTER_IMAGE=true ./stop_pymqi_exporter.sh
#
#   Remove all exporter build artifacts:
#       REMOVE_EXPORTER_IMAGE=true \
#       REMOVE_GENERATED_FILES=true \
#       ./stop_pymqi_exporter.sh
#
#   Full cleanup, including the MQ base image:
#       REMOVE_EXPORTER_IMAGE=true \
#       REMOVE_BASE_IMAGE=true \
#       REMOVE_GENERATED_FILES=true \
#       REMOVE_NETWORK=true \
#       ./stop_pymqi_exporter.sh
# =============================================================================

set -Eeuo pipefail

###############################################################################
# Paths
###############################################################################

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

GENERATED_DIR="${SCRIPT_DIR}/mq-pymqi-exporter"
GENERATED_DOCKERFILE="${GENERATED_DIR}/Dockerfile"
GENERATED_ENTRYPOINT="${GENERATED_DIR}/docker-entrypoint.sh"

###############################################################################
# Settings
###############################################################################

CONTAINER_NAME="${CONTAINER_NAME:-mq-pymqi-exporter}"
EXPORTER_IMAGE="${EXPORTER_IMAGE:-mq-pymqi-exporter:latest}"
BASE_IMAGE="${BASE_IMAGE:-mq-local-monitoring:latest}"
DOCKER_NETWORK="${DOCKER_NETWORK:-docker_build_default}"

REMOVE_CONTAINER="${REMOVE_CONTAINER:-true}"
REMOVE_EXPORTER_IMAGE="${REMOVE_EXPORTER_IMAGE:-false}"
REMOVE_BASE_IMAGE="${REMOVE_BASE_IMAGE:-false}"
REMOVE_GENERATED_FILES="${REMOVE_GENERATED_FILES:-false}"
REMOVE_NETWORK="${REMOVE_NETWORK:-false}"

###############################################################################
# Logging
###############################################################################

log_info() {
    printf '[INFO] %s\n' "$*"
}

log_warn() {
    printf '[WARN] %s\n' "$*" >&2
}

log_error() {
    printf '[ERROR] %s\n' "$*" >&2
}

die() {
    log_error "$*"
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 ||
        die "Required command was not found: $1"
}

is_true() {
    case "${1,,}" in
        true|yes|y|1|on)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

on_exit() {
    local exit_code=$?

    if (( exit_code != 0 )); then
        log_error "Stop operation failed with exit code ${exit_code}."
    fi

    exit "${exit_code}"
}

trap on_exit EXIT

###############################################################################
# Validate Docker
###############################################################################

require_command docker

###############################################################################
# Inspect current state
###############################################################################

CONTAINER_EXISTS=false
CONTAINER_RUNNING=false

if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    CONTAINER_EXISTS=true

    CONTAINER_RUNNING="$(
        docker container inspect \
            --format '{{.State.Running}}' \
            "${CONTAINER_NAME}"
    )"
fi

###############################################################################
# Stop exporter container
###############################################################################

if [[ "${CONTAINER_EXISTS}" == "true" ]]; then
    if [[ "${CONTAINER_RUNNING}" == "true" ]]; then
        log_info "Stopping exporter container: ${CONTAINER_NAME}"

        docker stop \
            --time 20 \
            "${CONTAINER_NAME}" >/dev/null

        log_info "Exporter container stopped."
    else
        log_info "Exporter container is already stopped: ${CONTAINER_NAME}"
    fi
else
    log_info "Exporter container does not exist: ${CONTAINER_NAME}"
fi

###############################################################################
# Remove exporter container
###############################################################################

if is_true "${REMOVE_CONTAINER}"; then
    if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
        log_info "Removing exporter container: ${CONTAINER_NAME}"

        docker rm \
            --force \
            "${CONTAINER_NAME}" >/dev/null

        log_info "Exporter container removed."
    else
        log_info "No exporter container to remove."
    fi
else
    log_info "Leaving stopped exporter container in place."
fi

###############################################################################
# Remove exporter image
###############################################################################

if is_true "${REMOVE_EXPORTER_IMAGE}"; then
    if docker image inspect "${EXPORTER_IMAGE}" >/dev/null 2>&1; then
        log_info "Removing exporter image: ${EXPORTER_IMAGE}"

        if docker image rm "${EXPORTER_IMAGE}" >/dev/null; then
            log_info "Exporter image removed."
        else
            log_warn "Unable to remove exporter image normally."
            log_warn "Another container may still reference it."

            log_info "Attempting forced exporter image removal..."

            docker image rm \
                --force \
                "${EXPORTER_IMAGE}" >/dev/null

            log_info "Exporter image forcibly removed."
        fi
    else
        log_info "Exporter image does not exist: ${EXPORTER_IMAGE}"
    fi
else
    log_info "Leaving exporter image in place: ${EXPORTER_IMAGE}"
fi

###############################################################################
# Remove generated Docker build files
###############################################################################

if is_true "${REMOVE_GENERATED_FILES}"; then
    if [[ -d "${GENERATED_DIR}" ]]; then
        log_info "Removing generated build directory: ${GENERATED_DIR}"

        rm -rf -- "${GENERATED_DIR}"

        log_info "Generated Dockerfile and entrypoint removed."
    else
        log_info "Generated build directory does not exist: ${GENERATED_DIR}"
    fi
else
    log_info "Leaving generated build files in place."

    [[ -f "${GENERATED_DOCKERFILE}" ]] &&
        log_info "  Dockerfile: ${GENERATED_DOCKERFILE}"

    [[ -f "${GENERATED_ENTRYPOINT}" ]] &&
        log_info "  Entrypoint: ${GENERATED_ENTRYPOINT}"
fi

###############################################################################
# Remove IBM MQ base image
###############################################################################

if is_true "${REMOVE_BASE_IMAGE}"; then
    if docker image inspect "${BASE_IMAGE}" >/dev/null 2>&1; then
        log_info "Removing IBM MQ base image: ${BASE_IMAGE}"

        if docker image rm "${BASE_IMAGE}" >/dev/null; then
            log_info "IBM MQ base image removed."
        else
            log_warn "Unable to remove IBM MQ base image."
            log_warn "Other images or containers may still depend on it."
            log_warn "The base image was not forcibly removed."
        fi
    else
        log_info "IBM MQ base image does not exist: ${BASE_IMAGE}"
    fi
else
    log_info "Leaving IBM MQ base image in place: ${BASE_IMAGE}"
fi

###############################################################################
# Remove Docker network
###############################################################################

if is_true "${REMOVE_NETWORK}"; then
    if docker network inspect "${DOCKER_NETWORK}" >/dev/null 2>&1; then
        NETWORK_CONTAINERS="$(
            docker network inspect \
                --format '{{len .Containers}}' \
                "${DOCKER_NETWORK}"
        )"

        if [[ "${NETWORK_CONTAINERS}" == "0" ]]; then
            log_info "Removing Docker network: ${DOCKER_NETWORK}"

            docker network rm "${DOCKER_NETWORK}" >/dev/null

            log_info "Docker network removed."
        else
            log_warn "Docker network is still in use: ${DOCKER_NETWORK}"
            log_warn "Connected container count: ${NETWORK_CONTAINERS}"
            log_warn "The network was not removed."

            docker network inspect \
                --format \
                '{{range $id, $container := .Containers}}  {{$container.Name}} ({{$id}}){{println}}{{end}}' \
                "${DOCKER_NETWORK}" ||
                true
        fi
    else
        log_info "Docker network does not exist: ${DOCKER_NETWORK}"
    fi
else
    log_info "Leaving Docker network in place: ${DOCKER_NETWORK}"
fi

###############################################################################
# Final state
###############################################################################

printf '\n'
printf 'Stop Summary\n'
printf '%-30s %s\n' "Exporter container:" "${CONTAINER_NAME}"
printf '%-30s %s\n' "Exporter image:" "${EXPORTER_IMAGE}"
printf '%-30s %s\n' "IBM MQ base image:" "${BASE_IMAGE}"
printf '%-30s %s\n' "Docker network:" "${DOCKER_NETWORK}"
printf '%-30s %s\n' "Container removed:" "${REMOVE_CONTAINER}"
printf '%-30s %s\n' "Exporter image removed:" "${REMOVE_EXPORTER_IMAGE}"
printf '%-30s %s\n' "Base image removed:" "${REMOVE_BASE_IMAGE}"
printf '%-30s %s\n' "Generated files removed:" "${REMOVE_GENERATED_FILES}"
printf '%-30s %s\n' "Network removal requested:" "${REMOVE_NETWORK}"
printf '\n'

log_info "mq-pymqi-exporter stop operation completed."

trap - EXIT
