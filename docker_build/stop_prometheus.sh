#!/usr/bin/env bash
# =============================================================================
# Script Name : stop_prometheus.sh
# Description : Stop and remove the Prometheus container created by
#               build_prometheus.sh.
#
# Usage:
#   ./stop_prometheus.sh [options]
#
# Options:
#   -i   Also remove the locally built Prometheus Docker image
#   -d   Also remove persistent Prometheus metrics data
#   -c   Also remove generated configuration and Compose files
#   -a   Remove container, image, data, and generated files
#   -?   Show this help message
#
# Default behavior:
#   - Stops and removes the Prometheus container
#   - Preserves the Docker image
#   - Preserves Prometheus time-series data
#   - Preserves generated configuration files
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_NAME="prometheus-local-monitoring"
CONTAINER_NAME="prometheus-local-monitoring"
COMPOSE_PROJECT_NAME="prometheus_local_monitoring"

COMPOSE_FILE="$SCRIPT_DIR/docker-compose.prometheus.yml"
PROMETHEUS_DIR="$SCRIPT_DIR/prometheus"
DATA_DIR="$SCRIPT_DIR/prometheus-data"

REMOVE_IMAGE=false
REMOVE_DATA=false
REMOVE_CONFIG=false

print_usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  -i   Remove the locally built Docker image: $IMAGE_NAME
  -d   Remove persistent Prometheus data: $DATA_DIR
  -c   Remove generated Prometheus configuration and Compose files
  -a   Perform complete cleanup
  -?   Show this help message

Examples:
  $0
      Stop and remove only the Prometheus container.

  $0 -i
      Stop the container and remove its locally built image.

  $0 -d
      Stop the container and delete stored Prometheus metrics.

  $0 -a
      Remove the container, image, data, and generated files.
EOF
}

while getopts ":idca?" opt; do
    case "$opt" in
        i)
            REMOVE_IMAGE=true
            ;;
        d)
            REMOVE_DATA=true
            ;;
        c)
            REMOVE_CONFIG=true
            ;;
        a)
            REMOVE_IMAGE=true
            REMOVE_DATA=true
            REMOVE_CONFIG=true
            ;;
        ?)
            print_usage
            exit 0
            ;;
        *)
            print_usage >&2
            exit 1
            ;;
    esac
done

check_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERROR: Required command '$1' is not installed or not on PATH." >&2
        exit 1
    }
}

container_exists() {
    docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1
}

image_exists() {
    docker image inspect "$IMAGE_NAME" >/dev/null 2>&1
}

check_command docker

echo "Stopping Prometheus local monitoring..."
echo

# Prefer Docker Compose because it removes the resources associated with the
# Compose project in a consistent manner.
if [[ -f "$COMPOSE_FILE" ]] && docker compose version >/dev/null 2>&1; then
    echo "Stopping Compose project '$COMPOSE_PROJECT_NAME'..."

    if ! docker compose \
        -p "$COMPOSE_PROJECT_NAME" \
        -f "$COMPOSE_FILE" \
        down --remove-orphans; then
        echo "WARNING: Docker Compose cleanup failed." >&2
        echo "Attempting direct container removal..." >&2
    fi
else
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        echo "Compose file not found: $COMPOSE_FILE"
    else
        echo "Docker Compose v2 is unavailable."
    fi

    echo "Attempting direct container removal..."
fi

# Fallback in case the Compose command did not remove the named container.
if container_exists; then
    echo "Stopping and removing container '$CONTAINER_NAME'..."
    docker rm -f "$CONTAINER_NAME"
else
    echo "Container '$CONTAINER_NAME' is not present."
fi

# Optionally remove the locally built image.
if [[ "$REMOVE_IMAGE" == true ]]; then
    if image_exists; then
        echo "Removing Docker image '$IMAGE_NAME'..."

        if ! docker image rm "$IMAGE_NAME"; then
            echo "WARNING: Could not remove image '$IMAGE_NAME'." >&2
            echo "It may still be used by another container." >&2
        fi
    else
        echo "Docker image '$IMAGE_NAME' is not present."
    fi
else
    echo "Docker image preserved: $IMAGE_NAME"
fi

# Optionally remove persistent Prometheus time-series data.
if [[ "$REMOVE_DATA" == true ]]; then
    if [[ -d "$DATA_DIR" ]]; then
        echo "Removing Prometheus data directory '$DATA_DIR'..."
        rm -rf "$DATA_DIR"
    else
        echo "Prometheus data directory is already absent."
    fi
else
    echo "Prometheus data preserved: $DATA_DIR"
fi

# Optionally remove generated configuration and Compose files.
if [[ "$REMOVE_CONFIG" == true ]]; then
    if [[ -f "$COMPOSE_FILE" ]]; then
        echo "Removing Compose file '$COMPOSE_FILE'..."
        rm -f "$COMPOSE_FILE"
    fi

    if [[ -d "$PROMETHEUS_DIR" ]]; then
        echo "Removing generated Prometheus directory '$PROMETHEUS_DIR'..."
        rm -rf "$PROMETHEUS_DIR"
    fi
else
    echo "Generated configuration preserved:"
    echo "  $COMPOSE_FILE"
    echo "  $PROMETHEUS_DIR"
fi

echo
echo "Prometheus shutdown complete."