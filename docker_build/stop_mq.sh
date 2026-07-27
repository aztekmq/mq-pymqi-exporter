```bash
#!/usr/bin/env bash
# =============================================================================
# Script Name : stop_mq_qmgrs.sh
# Description : Stop and remove all IBM MQ queue-manager containers created by
#               build_mq_qmgrs.sh.
#
# Author      : rob lee
# License     : MIT (SPDX-License-Identifier: MIT)
#
# Usage:
#   ./stop_mq_qmgrs.sh [options]
#
# Options:
#   -d   Delete persisted IBM MQ data under ./data
#   -i   Remove the locally built mq-local-monitoring Docker image
#   -c   Remove the generated docker-compose.yml file
#   -n   Remove the Docker Compose network if it remains and is unused
#   -a   Complete cleanup: container, data, image, Compose file, and network
#   -?   Show this help message
#
# Default behavior:
#   - Stops and removes all queue-manager containers
#   - Removes Compose-managed resources
#   - Preserves IBM MQ data
#   - Preserves the custom Docker image
#   - Preserves docker-compose.yml
#
# WARNING:
#   The -d and -a options permanently delete persisted queue-manager data.
# =============================================================================

set -euo pipefail

# Resolve paths relative to this script rather than the caller's current
# working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
DATA_DIR="${SCRIPT_DIR}/data"
IMAGE_NAME="mq-local-monitoring"

REMOVE_DATA=false
REMOVE_IMAGE=false
REMOVE_COMPOSE=false
REMOVE_NETWORK=false

# --------- COLORS ---------
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[0;33m'
    CYAN=$'\033[0;36m'
    NC=$'\033[0m'
else
    RED=""
    GREEN=""
    YELLOW=""
    CYAN=""
    NC=""
fi

print_usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  -d   Delete persisted IBM MQ data:
       $DATA_DIR

  -i   Remove the locally built Docker image:
       $IMAGE_NAME

  -c   Remove the generated Compose file:
       $COMPOSE_FILE

  -n   Remove the Compose network if it is unused

  -a   Perform a complete cleanup

  -?   Show this help message

Examples:
  $0
      Stop and remove all MQ containers while preserving data and image.

  $0 -d
      Stop all containers and permanently delete persisted MQ data.

  $0 -i -c
      Stop all containers and remove the custom image and Compose file.

  $0 -a
      Remove containers, data, image, Compose file, and unused network.
EOF
}

while getopts ":dicna?" opt; do
    case "$opt" in
        d)
            REMOVE_DATA=true
            ;;
        i)
            REMOVE_IMAGE=true
            ;;
        c)
            REMOVE_COMPOSE=true
            ;;
        n)
            REMOVE_NETWORK=true
            ;;
        a)
            REMOVE_DATA=true
            REMOVE_IMAGE=true
            REMOVE_COMPOSE=true
            REMOVE_NETWORK=true
            ;;
        ?)
            print_usage
            exit 0
            ;;
        :)
            echo -e "${RED}ERROR: Option -$OPTARG requires an argument.${NC}" >&2
            print_usage >&2
            exit 1
            ;;
        *)
            echo -e "${RED}ERROR: Unknown option -$OPTARG.${NC}" >&2
            print_usage >&2
            exit 1
            ;;
    esac
done

check_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo -e "${RED}ERROR: Required command '$1' is not installed or not on PATH.${NC}" >&2
        exit 1
    }
}

check_command docker

if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}ERROR: Docker is not running or is not accessible.${NC}" >&2
    exit 1
fi

echo -e "${CYAN}Stopping IBM MQ queue-manager environment...${NC}"
echo

# Record the Compose network names before bringing down the stack.
COMPOSE_NETWORKS=()

if [[ -f "$COMPOSE_FILE" ]] && docker compose version >/dev/null 2>&1; then
    while IFS= read -r network; do
        [[ -n "$network" ]] && COMPOSE_NETWORKS+=("$network")
    done < <(
        docker compose \
            -f "$COMPOSE_FILE" \
            config --format json 2>/dev/null |
        python3 -c '
import json
import sys

try:
    config = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)

project = config.get("name", "")
for key, value in config.get("networks", {}).items():
    if isinstance(value, dict) and value.get("name"):
        print(value["name"])
    elif project:
        print(f"{project}_{key}")
' 2>/dev/null || true
    )

    echo -e "${CYAN}Stopping services defined in:${NC}"
    echo "  $COMPOSE_FILE"

    if docker compose \
        -f "$COMPOSE_FILE" \
        down --remove-orphans; then
        echo -e "${GREEN}Compose services stopped and removed.${NC}"
    else
        echo -e "${YELLOW}WARNING: Docker Compose cleanup failed.${NC}" >&2
        echo -e "${YELLOW}Attempting direct container cleanup.${NC}" >&2
    fi
else
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        echo -e "${YELLOW}Compose file not found:${NC}"
        echo "  $COMPOSE_FILE"
    else
        echo -e "${YELLOW}Docker Compose v2 is unavailable.${NC}"
    fi

    echo -e "${YELLOW}Attempting direct container cleanup.${NC}"
fi

# Find any remaining containers created from the custom MQ image.
mapfile -t IMAGE_CONTAINERS < <(
    docker ps -aq \
        --filter "ancestor=${IMAGE_NAME}" \
        2>/dev/null || true
)

if (( ${#IMAGE_CONTAINERS[@]} > 0 )); then
    echo
    echo -e "${CYAN}Removing remaining containers based on image '${IMAGE_NAME}'...${NC}"

    for container_id in "${IMAGE_CONTAINERS[@]}"; do
        container_name="$(
            docker inspect \
                --format '{{.Name}}' \
                "$container_id" 2>/dev/null |
            sed 's#^/##'
        )"

        if [[ -n "$container_name" ]]; then
            echo "  Removing $container_name"
        else
            echo "  Removing $container_id"
        fi

        docker rm -f "$container_id" >/dev/null
    done
fi

# Fallback for containers named qm1, qm2, qm3, etc. This catches containers
# when the image tag changed after they were created.
mapfile -t QM_CONTAINERS < <(
    docker ps -a \
        --format '{{.ID}} {{.Names}}' |
    awk '$2 ~ /^qm[0-9]+$/ {print $1}'
)

if (( ${#QM_CONTAINERS[@]} > 0 )); then
    echo
    echo -e "${CYAN}Removing remaining qm<number> containers...${NC}"

    for container_id in "${QM_CONTAINERS[@]}"; do
        container_name="$(
            docker inspect \
                --format '{{.Name}}' \
                "$container_id" 2>/dev/null |
            sed 's#^/##'
        )"

        echo "  Removing ${container_name:-$container_id}"
        docker rm -f "$container_id" >/dev/null
    done
fi

# Verify that no matching containers remain.
mapfile -t REMAINING_CONTAINERS < <(
    docker ps -a \
        --format '{{.Names}} {{.Image}}' |
    awk -v image="$IMAGE_NAME" \
        '$1 ~ /^qm[0-9]+$/ || $2 == image {print $1}'
)

if (( ${#REMAINING_CONTAINERS[@]} > 0 )); then
    echo
    echo -e "${RED}WARNING: Some matching containers remain:${NC}" >&2

    for container_name in "${REMAINING_CONTAINERS[@]}"; do
        echo "  $container_name" >&2
    done
else
    echo
    echo -e "${GREEN}All IBM MQ queue-manager containers have been stopped and removed.${NC}"
fi

# --------- Optional Data Cleanup ---------
if [[ "$REMOVE_DATA" == true ]]; then
    echo
    echo -e "${YELLOW}Deleting persisted IBM MQ data:${NC}"
    echo "  $DATA_DIR"

    if [[ -d "$DATA_DIR" ]]; then
        if rm -rf "$DATA_DIR" 2>/dev/null; then
            echo -e "${GREEN}IBM MQ data directory removed.${NC}"
        else
            echo -e "${YELLOW}Standard removal failed; retrying with sudo...${NC}"

            if command -v sudo >/dev/null 2>&1; then
                sudo rm -rf "$DATA_DIR"
                echo -e "${GREEN}IBM MQ data directory removed.${NC}"
            else
                echo -e "${RED}ERROR: Could not remove '$DATA_DIR' and sudo is unavailable.${NC}" >&2
                exit 1
            fi
        fi
    else
        echo "Data directory is already absent."
    fi
else
    echo -e "${CYAN}IBM MQ data preserved:${NC}"
    echo "  $DATA_DIR"
fi

# --------- Optional Image Cleanup ---------
if [[ "$REMOVE_IMAGE" == true ]]; then
    echo
    echo -e "${CYAN}Removing Docker image '${IMAGE_NAME}'...${NC}"

    if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
        if docker image rm "$IMAGE_NAME"; then
            echo -e "${GREEN}Docker image removed.${NC}"
        else
            echo -e "${RED}WARNING: Could not remove image '${IMAGE_NAME}'.${NC}" >&2
            echo "It may still be referenced by another container." >&2
        fi
    else
        echo "Docker image is already absent."
    fi
else
    echo -e "${CYAN}Docker image preserved:${NC}"
    echo "  $IMAGE_NAME"
fi

# --------- Optional Network Cleanup ---------
if [[ "$REMOVE_NETWORK" == true ]]; then
    echo
    echo -e "${CYAN}Checking Compose networks...${NC}"

    # If network discovery failed, check the most likely default network name.
    if (( ${#COMPOSE_NETWORKS[@]} == 0 )); then
        project_name="$(basename "$SCRIPT_DIR" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '_')"
        COMPOSE_NETWORKS+=("${project_name}_default")
    fi

    for network_name in "${COMPOSE_NETWORKS[@]}"; do
        if ! docker network inspect "$network_name" >/dev/null 2>&1; then
            echo "Network '$network_name' is already absent."
            continue
        fi

        attached_count="$(
            docker network inspect "$network_name" \
                --format '{{len .Containers}}' 2>/dev/null || echo "unknown"
        )"

        if [[ "$attached_count" == "0" ]]; then
            echo "Removing unused network '$network_name'..."
            docker network rm "$network_name" >/dev/null
            echo -e "${GREEN}Network removed.${NC}"
        else
            echo -e "${YELLOW}Network '$network_name' is still used by ${attached_count} container(s).${NC}"
            echo "The network was not removed."
        fi
    done
fi

# --------- Optional Compose File Cleanup ---------
if [[ "$REMOVE_COMPOSE" == true ]]; then
    echo
    echo -e "${CYAN}Removing generated Compose file...${NC}"

    if [[ -f "$COMPOSE_FILE" ]]; then
        rm -f "$COMPOSE_FILE"
        echo -e "${GREEN}Removed:${NC} $COMPOSE_FILE"
    else
        echo "Compose file is already absent."
    fi
else
    echo -e "${CYAN}Compose file preserved:${NC}"
    echo "  $COMPOSE_FILE"
fi

echo
echo -e "${GREEN}IBM MQ environment shutdown complete.${NC}"
```
