#!/bin/bash
# =============================================================================
# Script Name : stop_grafana.sh
# Description : Stop and remove the Grafana container started by
#               build_grafana.sh.
#
# Usage:
#   ./stop_grafana.sh [options]
#
# Options:
#   -r   Also remove the generated Docker Compose file
#   -d   Also remove local Grafana data and provisioning directories
#   -n   Also remove the shared Docker network if it is unused
#   -?   Show help
#
# Notes:
#   - By default, Grafana's local data is preserved.
#   - The external Prometheus network is preserved by default.
# =============================================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CONTAINER_NAME="grafana-local-monitoring"
COMPOSE_PROJECT_NAME="grafana_local_monitoring"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.grafana.yml"

GRAFANA_DIR="$SCRIPT_DIR/grafana"
GRAFANA_DATA_DIR="$SCRIPT_DIR/grafana-data"
NETWORK_NAME="prometheus_local_monitoring_default"

REMOVE_COMPOSE_FILE=false
REMOVE_DATA=false
REMOVE_NETWORK=false

print_usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  -r   Remove the generated Docker Compose file
  -d   Remove Grafana data, provisioning, and copied dashboards
  -n   Remove the shared Docker network if it is not in use
  -?   Show this help message

Examples:
  $0
      Stop and remove the Grafana container while preserving its data.

  $0 -r
      Stop Grafana and remove docker-compose.grafana.yml.

  $0 -d -r
      Stop Grafana and remove its local data and generated Compose file.

  $0 -d -r -n
      Perform a complete cleanup, including the shared network when unused.
EOF
}

while getopts ":rdn?" opt; do
    case "$opt" in
        r) REMOVE_COMPOSE_FILE=true ;;
        d) REMOVE_DATA=true ;;
        n) REMOVE_NETWORK=true ;;
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

check_command docker

echo "Stopping Grafana local monitoring..."

# Prefer Docker Compose because it removes the container and associated
# Compose resources consistently.
if [[ -f "$COMPOSE_FILE" ]] && docker compose version >/dev/null 2>&1; then
    echo "Stopping Compose project '$COMPOSE_PROJECT_NAME'..."

    if ! docker compose \
        -p "$COMPOSE_PROJECT_NAME" \
        -f "$COMPOSE_FILE" \
        down --remove-orphans; then
        echo "WARNING: Docker Compose cleanup failed. Trying direct container removal." >&2
    fi
else
    echo "Compose file not found or Docker Compose is unavailable."
    echo "Trying direct container removal..."
fi

# Fallback in case Compose did not remove the named container.
CONTAINER_ID="$(
    docker ps -aq \
        --filter "name=^/${CONTAINER_NAME}$" \
        2>/dev/null || true
)"

if [[ -n "$CONTAINER_ID" ]]; then
    echo "Stopping and removing container '$CONTAINER_NAME'..."
    docker rm -f "$CONTAINER_ID"
else
    echo "Container '$CONTAINER_NAME' is not present."
fi

if [[ "$REMOVE_COMPOSE_FILE" == true ]]; then
    if [[ -f "$COMPOSE_FILE" ]]; then
        echo "Removing Compose file '$COMPOSE_FILE'..."
        rm -f "$COMPOSE_FILE"
    else
        echo "Compose file is already absent."
    fi
fi

if [[ "$REMOVE_DATA" == true ]]; then
    echo "Removing local Grafana files..."

    if [[ -d "$GRAFANA_DATA_DIR" ]]; then
        rm -rf "$GRAFANA_DATA_DIR"
        echo "Removed '$GRAFANA_DATA_DIR'."
    fi

    if [[ -d "$GRAFANA_DIR" ]]; then
        rm -rf "$GRAFANA_DIR"
        echo "Removed '$GRAFANA_DIR'."
    fi
else
    echo "Grafana data was preserved:"
    echo "  $GRAFANA_DATA_DIR"
    echo "  $GRAFANA_DIR"
fi

if [[ "$REMOVE_NETWORK" == true ]]; then
    if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
        ATTACHED_CONTAINERS="$(
            docker network inspect "$NETWORK_NAME" \
                --format '{{len .Containers}}' 2>/dev/null || echo "unknown"
        )"

        if [[ "$ATTACHED_CONTAINERS" == "0" ]]; then
            echo "Removing unused network '$NETWORK_NAME'..."
            docker network rm "$NETWORK_NAME"
        else
            echo "WARNING: Network '$NETWORK_NAME' is still being used by" \
                 "$ATTACHED_CONTAINERS container(s)." >&2
            echo "WARNING: The network was not removed." >&2
        fi
    else
        echo "Network '$NETWORK_NAME' is not present."
    fi
fi

echo
echo "Grafana shutdown complete."