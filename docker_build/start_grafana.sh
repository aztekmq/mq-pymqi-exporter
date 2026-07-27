#!/bin/bash
# =============================================================================
# Script Name : build_grafana.sh
# Description : Build and start a local Grafana container connected to the
#               Prometheus stack used by this lab.
#
# Usage:
#   ./build_grafana.sh [-P grafana_port] [-u prometheus_url] [-n network_name]
#                      [-U admin_user] [-W admin_password]
#
# Defaults:
#   grafana_port      3000
#   prometheus_url    http://prometheus-local-monitoring:9090
#   network_name      prometheus_local_monitoring_default
#   admin_user        admin
#   admin_password    admin
# =============================================================================

set -u

IMAGE_NAME="grafana/grafana:latest"
CONTAINER_NAME="grafana-local-monitoring"
COMPOSE_PROJECT_NAME="grafana_local_monitoring"
COMPOSE_FILE="docker-compose.grafana.yml"

GRAFANA_DIR="./grafana"
GRAFANA_DATA_DIR="./grafana-data"
PROVISIONING_DIR="$GRAFANA_DIR/provisioning"
DATASOURCES_DIR="$PROVISIONING_DIR/datasources"
DASHBOARDS_CFG_DIR="$PROVISIONING_DIR/dashboards"
DASHBOARDS_DIR="$GRAFANA_DIR/dashboards"
REPO_DASHBOARDS_DIR="../dashboards"

GRAFANA_PORT=3000
PROMETHEUS_URL="http://prometheus-local-monitoring:9090"
NETWORK_NAME="prometheus_local_monitoring_default"
ADMIN_USER="admin"
ADMIN_PASSWORD="admin"

print_usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  -P GRAFANA_PORT      Grafana UI listen port (default: $GRAFANA_PORT)
  -u PROMETHEUS_URL    Grafana datasource URL for Prometheus (default: $PROMETHEUS_URL)
  -n NETWORK_NAME      Docker network shared with Prometheus (default: $NETWORK_NAME)
  -U ADMIN_USER        Grafana admin username (default: $ADMIN_USER)
  -W ADMIN_PASSWORD    Grafana admin password (default: $ADMIN_PASSWORD)
  -?                   Show this help message
EOF
}

while getopts ":P:u:n:U:W:?" opt; do
  case "$opt" in
    P) GRAFANA_PORT="$OPTARG" ;;
    u) PROMETHEUS_URL="$OPTARG" ;;
    n) NETWORK_NAME="$OPTARG" ;;
    U) ADMIN_USER="$OPTARG" ;;
    W) ADMIN_PASSWORD="$OPTARG" ;;
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
check_command python3

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose support is not available. Ensure Docker with Compose v2 is installed." >&2
  exit 1
fi

if [[ ! "$GRAFANA_PORT" =~ ^[0-9]+$ ]]; then
  echo "ERROR: Invalid Grafana port '$GRAFANA_PORT'." >&2
  exit 1
fi

if docker ps -aq --filter "name=^${CONTAINER_NAME}$" >/dev/null 2>&1; then
  old_container=$(docker ps -aq --filter "name=^${CONTAINER_NAME}$")
  if [[ -n "$old_container" ]]; then
    echo "Removing existing container $CONTAINER_NAME..."
    docker rm -f "$old_container" >/dev/null 2>&1 || true
  fi
fi

if ! check_port_available "$GRAFANA_PORT"; then
  echo "ERROR: Grafana port $GRAFANA_PORT is already in use by another process/container." >&2
  exit 1
fi

if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
  echo "Shared network '$NETWORK_NAME' not found. Creating it now..."
  docker network create "$NETWORK_NAME" >/dev/null
fi

echo "Preparing Grafana provisioning files..."
mkdir -p "$DATASOURCES_DIR" "$DASHBOARDS_CFG_DIR" "$DASHBOARDS_DIR" "$GRAFANA_DATA_DIR"
chmod -R 0777 "$GRAFANA_DATA_DIR" 2>/dev/null || true

if compgen -G "$REPO_DASHBOARDS_DIR/*.json" >/dev/null 2>&1; then
  cp -f "$REPO_DASHBOARDS_DIR"/*.json "$DASHBOARDS_DIR"/
fi

cat > "$DATASOURCES_DIR/prometheus.yml" <<EOF
apiVersion: 1
deleteDatasources:
  - name: Prometheus
    orgId: 1
datasources:
  - name: Prometheus
    uid: "000000001"
    orgId: 1
    type: prometheus
    access: proxy
    url: $PROMETHEUS_URL
    isDefault: true
    editable: true
EOF

cat > "$DASHBOARDS_CFG_DIR/dashboard-provider.yml" <<EOF
apiVersion: 1
providers:
  - name: IBM MQ Containers
    orgId: 1
    folder: IBM MQ Containers
    type: file
    allowUiUpdates: true
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
EOF

cat > "$COMPOSE_FILE" <<EOF
services:
  grafana:
    image: $IMAGE_NAME
    container_name: $CONTAINER_NAME
    ports:
      - "127.0.0.1:$GRAFANA_PORT:3000"
    environment:
      - GF_SECURITY_ADMIN_USER=$ADMIN_USER
      - GF_SECURITY_ADMIN_PASSWORD=$ADMIN_PASSWORD
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - ./grafana-data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning
      - ./grafana/dashboards:/var/lib/grafana/dashboards
    networks:
      - monitoring
    restart: unless-stopped

networks:
  monitoring:
    external: true
    name: $NETWORK_NAME
EOF

echo "Starting Grafana container..."
docker compose -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" up -d

if [[ $? -ne 0 ]]; then
  echo "ERROR: Failed to start Grafana container." >&2
  exit 1
fi

if [[ "$ADMIN_USER" == "admin" ]]; then
  timeout 30s docker exec "$CONTAINER_NAME" grafana cli admin reset-admin-password "$ADMIN_PASSWORD" >/dev/null 2>&1 || {
    echo "WARNING: Grafana started, but the admin password reset command failed." >&2
  }
fi

GRAFANA_URL="http://127.0.0.1:$GRAFANA_PORT" \
GRAFANA_USER="$ADMIN_USER" \
GRAFANA_PASSWORD="$ADMIN_PASSWORD" \
DASHBOARDS_DIR="$DASHBOARDS_DIR" \
DASHBOARD_FOLDER="IBM MQ Containers" \
python3 <<'PY'
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

base_url = os.environ["GRAFANA_URL"].rstrip("/")
user = os.environ["GRAFANA_USER"]
password = os.environ["GRAFANA_PASSWORD"]
dashboards_dir = Path(os.environ["DASHBOARDS_DIR"])
folder_title = os.environ["DASHBOARD_FOLDER"]
auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def request(method, path, body=None, timeout=20):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{base_url}{path}", data=data, method=method)
    req.add_header("Authorization", auth)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode()
            return resp.status, json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"raw": text}
        return exc.code, payload
    except (ConnectionError, OSError, TimeoutError, urllib.error.URLError) as exc:
        return 0, {"error": str(exc)}


for _ in range(30):
    status, _ = request("GET", "/api/health", timeout=3)
    if status == 200:
        break
    time.sleep(1)
else:
    raise SystemExit("WARNING: Grafana API was not ready; skipped v2 dashboard import.")

status, folders = request("GET", "/api/folders")
if status != 200:
    raise SystemExit(f"WARNING: Could not list Grafana folders; skipped v2 dashboard import: {folders}")

folder_uid = next((folder["uid"] for folder in folders if folder.get("title") == folder_title), None)
if not folder_uid:
    status, folder = request("POST", "/api/folders", {"title": folder_title})
    if status not in (200, 201):
        raise SystemExit(f"WARNING: Could not create Grafana folder; skipped v2 dashboard import: {folder}")
    folder_uid = folder["uid"]


def dashboard_name(path):
    return re.sub(r"[^a-z0-9-]+", "-", path.stem.lower().replace("_", "-")).strip("-")


def normalize_datasources(value):
    if isinstance(value, dict):
        if value.get("name") == "PBFA97CFB590B2093":
            value["name"] = "000000001"
        for child in value.values():
            normalize_datasources(child)
    elif isinstance(value, list):
        for child in value:
            normalize_datasources(child)


imported = 0
for path in sorted(dashboards_dir.glob("*.json")):
    spec = json.loads(path.read_text())
    if "elements" not in spec:
        continue
    normalize_datasources(spec)
    name = dashboard_name(path)
    body = {
        "kind": "Dashboard",
        "apiVersion": "dashboard.grafana.app/v2",
        "metadata": {
            "name": name,
            "namespace": "default",
            "annotations": {"grafana.app/folder": folder_uid},
        },
        "spec": spec,
    }
    path_url = f"/apis/dashboard.grafana.app/v2/namespaces/default/dashboards/{name}"
    status, payload = request("PUT", path_url, body)
    if status == 404:
        status, payload = request("POST", "/apis/dashboard.grafana.app/v2/namespaces/default/dashboards", body)
    if status not in (200, 201):
        raise SystemExit(f"WARNING: Failed to import {path.name}: {payload}")
    imported += 1

print(f"Imported {imported} v2 Grafana dashboards into '{folder_title}'.")
PY

echo "Grafana is ready."
echo ""
echo "Deployment Summary:"
echo "Grafana UI      : http://localhost:$GRAFANA_PORT/"
echo "Login           : $ADMIN_USER / $ADMIN_PASSWORD"
echo "Datasource URL  : $PROMETHEUS_URL"
echo "Dashboard dir   : $DASHBOARDS_DIR"
echo "Container name  : $CONTAINER_NAME"
