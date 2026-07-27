#!/bin/bash
# =============================================================================
# Script Name : build_prometheus.sh
# Description : Build and start a local Prometheus container that scrapes the
#               exporter over their shared Docker network.
#
# Usage:
#   ./start_prometheus.sh [-h host] [-p scrape_ports] [-u scrape_path]
#                         [-P prometheus_port] [-i scrape_interval]
#                         [-e evaluation_interval] [-n exporter_network]
#
# Defaults:
#   host               mq-pymqi-exporter
#   scrape_ports       9157
#   scrape_path        /metrics
#   prometheus_port    9091
#   scrape_interval    15s
#   evaluation_interval 15s
#   exporter_network   docker_build_default
#
# Example:
#   ./start_prometheus.sh
# =============================================================================

set -u

IMAGE_NAME="prometheus-local-monitoring"
CONTAINER_NAME="prometheus-local-monitoring"
PROMETHEUS_DIR="./prometheus"
DATA_DIR="./prometheus-data"
CONFIG_FILE="$PROMETHEUS_DIR/prometheus.yml"
DOCKERFILE="$PROMETHEUS_DIR/Dockerfile"
COMPOSE_FILE="docker-compose.prometheus.yml"

SCRAPE_HOST="mq-pymqi-exporter"
SCRAPE_PORTS="9157"
SCRAPE_PATH="/metrics"
PROMETHEUS_PORT=9091
SCRAPE_INTERVAL="15s"
EVALUATION_INTERVAL="15s"
EXPORTER_NETWORK="docker_build_default"

print_usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  -h HOST               Prometheus scrape host (default: $SCRAPE_HOST)
  -p SCRAPE_PORTS       Comma-separated scrape ports (default: $SCRAPE_PORTS)
  -u SCRAPE_PATH        Prometheus scrape path (default: $SCRAPE_PATH)
  -P PROMETHEUS_PORT    Prometheus UI listen port (default: $PROMETHEUS_PORT)
  -i SCRAPE_INTERVAL    Prometheus scrape interval (default: $SCRAPE_INTERVAL)
  -e EVALUATION_INTERVAL Prometheus evaluation interval (default: $EVALUATION_INTERVAL)
  -n EXPORTER_NETWORK   Docker network shared with exporter (default: $EXPORTER_NETWORK)
  -?                    Show this help message
EOF
}

while getopts ":h:p:u:P:i:e:n:?" opt; do
  case "$opt" in
    h) SCRAPE_HOST="$OPTARG" ;;
    p) SCRAPE_PORTS="$OPTARG" ;;
    u) SCRAPE_PATH="$OPTARG" ;;
    P) PROMETHEUS_PORT="$OPTARG" ;;
    i) SCRAPE_INTERVAL="$OPTARG" ;;
    e) EVALUATION_INTERVAL="$OPTARG" ;;
    n) EXPORTER_NETWORK="$OPTARG" ;;
    ?) print_usage ; exit 0 ;;
    *) print_usage ; exit 1 ;;
  esac
 done

check_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: Required command '$1' is not installed or not on PATH." >&2
    exit 1
  }
}

check_port_available() {
  local port="$1"
  if ss -ltn | grep -qE ":$port(\s|$)"; then
    return 1
  fi
  return 0
}

check_command docker

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose support is not available. Ensure Docker with Compose v2 is installed." >&2
  exit 1
fi

if ! docker network inspect "$EXPORTER_NETWORK" >/dev/null 2>&1; then
  echo "ERROR: Exporter Docker network '$EXPORTER_NETWORK' does not exist." >&2
  echo "Start the MQ/exporter stack first or select its network with -n." >&2
  exit 1
fi

# If our Prometheus container already exists, remove it first so port checks
# do not falsely fail when reconfiguring scrape targets.
if docker ps -aq --filter "name=^${CONTAINER_NAME}$" >/dev/null 2>&1; then
  old_container=$(docker ps -aq --filter "name=^${CONTAINER_NAME}$")
  if [[ -n "$old_container" ]]; then
    echo "Removing existing container $CONTAINER_NAME..."
    docker rm -f "$old_container" >/dev/null 2>&1 || true
  fi
fi

if ! check_port_available "$PROMETHEUS_PORT"; then
  echo "ERROR: Prometheus UI port $PROMETHEUS_PORT is already in use by another process/container. Cannot continue." >&2
  exit 1
fi

echo "Preparing Prometheus build context..."
mkdir -p "$PROMETHEUS_DIR"
mkdir -p "$DATA_DIR"
chmod -R 0777 "$DATA_DIR" 2>/dev/null || true

cat > "$CONFIG_FILE" <<EOF
global:
  scrape_interval: $SCRAPE_INTERVAL
  evaluation_interval: $EVALUATION_INTERVAL

scrape_configs:
  - job_name: 'ibmmq_metrics_exporter'
    metrics_path: '$SCRAPE_PATH'
    static_configs:
      - targets:
EOF

IFS=',' read -r -a scrape_port_array <<< "$SCRAPE_PORTS"
for raw_port in "${scrape_port_array[@]}"; do
  port="$(echo "$raw_port" | xargs)"
  if [[ -z "$port" ]]; then
    continue
  fi
  if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Invalid scrape port '$port'. Use comma-separated numeric ports, e.g. 9158,9159." >&2
    exit 1
  fi
  echo "        - '$SCRAPE_HOST:$port'" >> "$CONFIG_FILE"
done

if ! grep -q "$SCRAPE_HOST:" "$CONFIG_FILE"; then
  echo "ERROR: No valid scrape ports were provided." >&2
  exit 1
fi

cat > "$DOCKERFILE" <<EOF
FROM prom/prometheus:latest
COPY prometheus.yml /etc/prometheus/prometheus.yml
EOF

COMPOSE_PROJECT_NAME="prometheus_local_monitoring"

cat > "$COMPOSE_FILE" <<EOF
services:
  prometheus:
    build:
      context: ./prometheus
    image: $IMAGE_NAME
    container_name: $CONTAINER_NAME
    ports:
      - "127.0.0.1:$PROMETHEUS_PORT:9090"
    volumes:
      - ./prometheus-data:/prometheus
    networks:
      - default
      - exporter
    restart: unless-stopped

networks:
  exporter:
    external: true
    name: $EXPORTER_NETWORK
EOF

echo "Building local Prometheus image..."
docker build -t "$IMAGE_NAME" "$PROMETHEUS_DIR"

echo "Starting Prometheus container..."
docker compose -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" up -d

if [[ $? -ne 0 ]]; then
  echo "ERROR: Failed to start Prometheus container." >&2
  exit 1
fi

echo "Prometheus is ready."
echo ""
echo "Deployment Summary:"
echo "Prometheus UI  : http://localhost:$PROMETHEUS_PORT/"
echo "Scrape targets : $SCRAPE_HOST:${SCRAPE_PORTS//,/ , $SCRAPE_HOST:}$SCRAPE_PATH"
echo "Exporter network: $EXPORTER_NETWORK"
echo "Image name     : $IMAGE_NAME"
echo "Container name : $CONTAINER_NAME"
