#!/usr/bin/env bash
# =============================================================================
# Script Name : docker_container_tool.sh
# Description : Interactive utility for inspecting and managing running Docker
#               containers.
#
# Features:
#   - Lists running containers in a numbered menu
#   - Shows recent logs
#   - Follows live logs
#   - Opens a shell inside the container
#   - Displays container stats
#   - Shows running processes
#   - Displays port mappings
#   - Displays environment variables
#   - Shows health and state information
#   - Runs a custom command inside the container
#   - Copies files to or from the container
#   - Restarts, stops, or removes a container
#
# Usage:
#   chmod +x docker_container_tool.sh
#   ./docker_container_tool.sh
#
# Optional environment variables:
#   DEFAULT_LOG_LINES=100
# =============================================================================

set -Eeuo pipefail

DEFAULT_LOG_LINES="${DEFAULT_LOG_LINES:-100}"

SELECTED_CONTAINER=""
SELECTED_CONTAINER_ID=""

###############################################################################
# Colors
###############################################################################

if [[ -t 1 ]]; then
    COLOR_RESET=$'\033[0m'
    COLOR_BOLD=$'\033[1m'
    COLOR_RED=$'\033[31m'
    COLOR_GREEN=$'\033[32m'
    COLOR_YELLOW=$'\033[33m'
    COLOR_BLUE=$'\033[34m'
    COLOR_CYAN=$'\033[36m'
else
    COLOR_RESET=""
    COLOR_BOLD=""
    COLOR_RED=""
    COLOR_GREEN=""
    COLOR_YELLOW=""
    COLOR_BLUE=""
    COLOR_CYAN=""
fi

###############################################################################
# Logging
###############################################################################

log_info() {
    printf '%s[INFO]%s %s\n' \
        "${COLOR_GREEN}" \
        "${COLOR_RESET}" \
        "$*"
}

log_warn() {
    printf '%s[WARN]%s %s\n' \
        "${COLOR_YELLOW}" \
        "${COLOR_RESET}" \
        "$*" >&2
}

log_error() {
    printf '%s[ERROR]%s %s\n' \
        "${COLOR_RED}" \
        "${COLOR_RESET}" \
        "$*" >&2
}

die() {
    log_error "$*"
    exit 1
}

pause() {
    printf '\n'
    read -r -p "Press Enter to continue..." _
}

confirm() {
    local prompt="${1:-Continue?}"
    local answer

    read -r -p "${prompt} [y/N]: " answer

    case "${answer,,}" in
        y|yes)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

###############################################################################
# Validation
###############################################################################

command -v docker >/dev/null 2>&1 ||
    die "Docker was not found on PATH."

if ! docker info >/dev/null 2>&1; then
    die "Docker is unavailable or your user cannot access the Docker daemon."
fi

###############################################################################
# Display helpers
###############################################################################

print_header() {
    clear 2>/dev/null || true

    printf '%s%sDocker Container Utility%s\n' \
        "${COLOR_BOLD}" \
        "${COLOR_CYAN}" \
        "${COLOR_RESET}"

    printf '%s\n\n' \
        "============================================================"
}

print_selected_container() {
    if [[ -n "${SELECTED_CONTAINER}" ]]; then
        printf '%sSelected container:%s %s (%s)\n\n' \
            "${COLOR_BOLD}" \
            "${COLOR_RESET}" \
            "${SELECTED_CONTAINER}" \
            "${SELECTED_CONTAINER_ID}"
    fi
}

container_exists() {
    docker container inspect "$1" >/dev/null 2>&1
}

container_running() {
    [[ "$(
        docker container inspect \
            --format '{{.State.Running}}' \
            "$1" 2>/dev/null
    )" == "true" ]]
}

###############################################################################
# Container selection
###############################################################################

select_container() {
    local include_stopped="${1:-false}"
    local -a docker_ps_args=()
    local -a container_ids=()
    local selection
    local index
    local container_id
    local container_name
    local container_image
    local container_status
    local container_ports

    if [[ "${include_stopped}" == "true" ]]; then
        docker_ps_args=(-a)
    fi

    mapfile -t container_ids < <(
        docker ps \
            "${docker_ps_args[@]}" \
            --format '{{.ID}}'
    )

    if (( ${#container_ids[@]} == 0 )); then
        if [[ "${include_stopped}" == "true" ]]; then
            log_warn "No Docker containers were found."
        else
            log_warn "No running Docker containers were found."
        fi

        return 1
    fi

    print_header

    if [[ "${include_stopped}" == "true" ]]; then
        printf '%sAll containers:%s\n\n' \
            "${COLOR_BOLD}" \
            "${COLOR_RESET}"
    else
        printf '%sRunning containers:%s\n\n' \
            "${COLOR_BOLD}" \
            "${COLOR_RESET}"
    fi

    printf '%-5s %-14s %-28s %-25s %-24s %s\n' \
        "NUM" \
        "ID" \
        "NAME" \
        "IMAGE" \
        "STATUS" \
        "PORTS"

    printf '%s\n' \
        "------------------------------------------------------------------------------------------------------------------------"

    index=1

    for container_id in "${container_ids[@]}"; do
        container_name="$(
            docker inspect \
                --format '{{.Name}}' \
                "${container_id}"
        )"

        # docker inspect returns the name with a leading slash.
        container_name="${container_name#/}"

        container_image="$(
            docker inspect \
                --format '{{.Config.Image}}' \
                "${container_id}"
        )"

        container_status="$(
            docker ps \
                "${docker_ps_args[@]}" \
                --filter "id=${container_id}" \
                --format '{{.Status}}'
        )"

        container_ports="$(
            docker ps \
                "${docker_ps_args[@]}" \
                --filter "id=${container_id}" \
                --format '{{.Ports}}'
        )"

        printf '%-5s %-14s %-28s %-25s %-24s %s\n' \
            "${index}" \
            "${container_id:0:12}" \
            "${container_name}" \
            "${container_image}" \
            "${container_status}" \
            "${container_ports}"

        ((index += 1))
    done

    printf '\n'
    read -r -p "Select a container number, or q to quit: " selection

    if [[ "${selection,,}" == "q" ]]; then
        exit 0
    fi

    if [[ ! "${selection}" =~ ^[0-9]+$ ]]; then
        log_error "Selection must be a number."
        pause
        return 1
    fi

    if (( selection < 1 || selection > ${#container_ids[@]} )); then
        log_error "Selection is outside the valid range."
        pause
        return 1
    fi

    SELECTED_CONTAINER_ID="${container_ids[$((selection - 1))]}"

    SELECTED_CONTAINER="$(
        docker inspect \
            --format '{{.Name}}' \
            "${SELECTED_CONTAINER_ID}"
    )"

    SELECTED_CONTAINER="${SELECTED_CONTAINER#/}"

    return 0
}

###############################################################################
# Logs
###############################################################################

show_logs() {
    local lines

    read -r -p \
        "Number of log lines [${DEFAULT_LOG_LINES}]: " \
        lines

    lines="${lines:-${DEFAULT_LOG_LINES}}"

    if [[ ! "${lines}" =~ ^[0-9]+$ ]]; then
        log_error "Log line count must be a positive number."
        pause
        return
    fi

    printf '\n'
    log_info "Showing the last ${lines} lines from ${SELECTED_CONTAINER}."
    printf '\n'

    docker logs \
        --timestamps \
        --tail "${lines}" \
        "${SELECTED_CONTAINER}" 2>&1 |
        less -R +G
}

follow_logs() {
    local lines

    read -r -p \
        "Initial number of log lines [${DEFAULT_LOG_LINES}]: " \
        lines

    lines="${lines:-${DEFAULT_LOG_LINES}}"

    if [[ ! "${lines}" =~ ^[0-9]+$ ]]; then
        log_error "Log line count must be a positive number."
        pause
        return
    fi

    printf '\n'
    log_info "Following logs for ${SELECTED_CONTAINER}."
    log_info "Press Ctrl+C to stop following logs."
    printf '\n'

    docker logs \
        --follow \
        --timestamps \
        --tail "${lines}" \
        "${SELECTED_CONTAINER}" 2>&1 || true
}

show_logs_since() {
    local since_value

    printf '\n'
    printf 'Examples:\n'
    printf '  10m       last 10 minutes\n'
    printf '  2h        last 2 hours\n'
    printf '  2026-07-26T12:00:00\n'
    printf '\n'

    read -r -p "Show logs since: " since_value

    if [[ -z "${since_value}" ]]; then
        log_warn "No time value entered."
        pause
        return
    fi

    docker logs \
        --timestamps \
        --since "${since_value}" \
        "${SELECTED_CONTAINER}" 2>&1 |
        less -R
}

search_logs() {
    local pattern
    local lines

    read -r -p "Search pattern: " pattern
    read -r -p "Number of recent lines [1000]: " lines

    lines="${lines:-1000}"

    if [[ -z "${pattern}" ]]; then
        log_warn "No search pattern entered."
        pause
        return
    fi

    if [[ ! "${lines}" =~ ^[0-9]+$ ]]; then
        log_error "Line count must be numeric."
        pause
        return
    fi

    printf '\n'

    docker logs \
        --timestamps \
        --tail "${lines}" \
        "${SELECTED_CONTAINER}" 2>&1 |
        grep --color=always -i -- "${pattern}" |
        less -R || true
}

###############################################################################
# Shell and commands
###############################################################################

open_shell() {
    local shell_path=""

    if ! container_running "${SELECTED_CONTAINER}"; then
        log_error "Container is not running: ${SELECTED_CONTAINER}"
        pause
        return
    fi

    for candidate in /bin/bash /usr/bin/bash /bin/sh /usr/bin/sh; do
        if docker exec "${SELECTED_CONTAINER}" \
            test -x "${candidate}" >/dev/null 2>&1; then
            shell_path="${candidate}"
            break
        fi
    done

    if [[ -z "${shell_path}" ]]; then
        log_error "No supported shell was found inside the container."
        pause
        return
    fi

    log_info "Opening ${shell_path} inside ${SELECTED_CONTAINER}."
    log_info "Type exit to return to this utility."
    printf '\n'

    docker exec \
        --interactive \
        --tty \
        "${SELECTED_CONTAINER}" \
        "${shell_path}"
}

run_command() {
    local command_text

    if ! container_running "${SELECTED_CONTAINER}"; then
        log_error "Container is not running: ${SELECTED_CONTAINER}"
        pause
        return
    fi

    read -r -p "Command to run inside the container: " command_text

    if [[ -z "${command_text}" ]]; then
        log_warn "No command entered."
        pause
        return
    fi

    printf '\n'

    docker exec \
        --interactive \
        "${SELECTED_CONTAINER}" \
        /bin/sh \
        -c "${command_text}" || true

    pause
}

###############################################################################
# Inspection
###############################################################################

show_summary() {
    docker container inspect \
        --format '
Container
---------
Name:             {{trimPrefix "/" .Name}}
ID:               {{.Id}}
Image:            {{.Config.Image}}
Created:          {{.Created}}
Status:           {{.State.Status}}
Running:          {{.State.Running}}
Started:          {{.State.StartedAt}}
Finished:         {{.State.FinishedAt}}
Exit code:        {{.State.ExitCode}}
Restart count:    {{.RestartCount}}
Restart policy:   {{.HostConfig.RestartPolicy.Name}}
Hostname:         {{.Config.Hostname}}
User:             {{.Config.User}}
Working directory: {{.Config.WorkingDir}}

Command
-------
Entrypoint: {{json .Config.Entrypoint}}
Command:    {{json .Config.Cmd}}

Network mode
------------
{{.HostConfig.NetworkMode}}

Networks
--------
{{range $name, $network := .NetworkSettings.Networks}}{{$name}}
  IP address: {{$network.IPAddress}}
  Gateway:    {{$network.Gateway}}
  Aliases:    {{json $network.Aliases}}
{{end}}

Health
------
{{if .State.Health}}Status: {{.State.Health.Status}}
{{range .State.Health.Log}}Exit={{.ExitCode}} Time={{.End}}
  {{.Output}}
{{end}}{{else}}No Docker health check configured.
{{end}}
' \
        "${SELECTED_CONTAINER}" |
        less -R
}

show_full_inspect() {
    docker container inspect "${SELECTED_CONTAINER}" |
        less -R
}

show_stats() {
    printf '\n'
    log_info "Displaying live resource usage."
    log_info "Press Ctrl+C to return."
    printf '\n'

    docker stats "${SELECTED_CONTAINER}" || true
}

show_one_time_stats() {
    docker stats \
        --no-stream \
        --format \
        'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}' \
        "${SELECTED_CONTAINER}"

    pause
}

show_processes() {
    printf '\n'
    docker top "${SELECTED_CONTAINER}" || true
    pause
}

show_ports() {
    printf '\n'
    docker port "${SELECTED_CONTAINER}" || true
    pause
}

show_environment() {
    docker container inspect \
        --format '{{range .Config.Env}}{{println .}}{{end}}' \
        "${SELECTED_CONTAINER}" |
        sort |
        less -R
}

show_mounts() {
    docker container inspect \
        --format '
{{range .Mounts}}
Type:        {{.Type}}
Source:      {{.Source}}
Destination: {{.Destination}}
Read-only:   {{not .RW}}
Propagation: {{.Propagation}}

{{end}}' \
        "${SELECTED_CONTAINER}" |
        less -R
}

show_networks() {
    docker container inspect \
        --format '
{{range $name, $network := .NetworkSettings.Networks}}
Network:    {{$name}}
IP address: {{$network.IPAddress}}
Gateway:    {{$network.Gateway}}
MAC:        {{$network.MacAddress}}
Aliases:    {{json $network.Aliases}}

{{end}}' \
        "${SELECTED_CONTAINER}" |
        less -R
}

show_health() {
    docker container inspect \
        --format '
Container: {{trimPrefix "/" .Name}}
State:     {{.State.Status}}

{{if .State.Health}}
Health:    {{.State.Health.Status}}

Recent health checks:
{{range .State.Health.Log}}
Started:   {{.Start}}
Finished:  {{.End}}
Exit code: {{.ExitCode}}
Output:
{{.Output}}
----------------------------------------
{{end}}
{{else}}
No Docker health check is configured.
{{end}}
' \
        "${SELECTED_CONTAINER}" |
        less -R
}

show_changes() {
    printf '\n'
    log_info "Filesystem changes made since the image was created:"
    printf '\n'

    docker diff "${SELECTED_CONTAINER}" |
        less -R
}

###############################################################################
# File copying
###############################################################################

copy_from_container() {
    local source_path
    local destination_path

    read -r -p "Container path to copy: " source_path
    read -r -p "Local destination path: " destination_path

    if [[ -z "${source_path}" || -z "${destination_path}" ]]; then
        log_error "Both source and destination are required."
        pause
        return
    fi

    docker cp \
        "${SELECTED_CONTAINER}:${source_path}" \
        "${destination_path}"

    log_info "Copied to: ${destination_path}"
    pause
}

copy_to_container() {
    local source_path
    local destination_path

    if ! container_running "${SELECTED_CONTAINER}"; then
        log_error "Container is not running: ${SELECTED_CONTAINER}"
        pause
        return
    fi

    read -r -p "Local path to copy: " source_path
    read -r -p "Container destination path: " destination_path

    if [[ -z "${source_path}" || -z "${destination_path}" ]]; then
        log_error "Both source and destination are required."
        pause
        return
    fi

    if [[ ! -e "${source_path}" ]]; then
        log_error "Local source does not exist: ${source_path}"
        pause
        return
    fi

    docker cp \
        "${source_path}" \
        "${SELECTED_CONTAINER}:${destination_path}"

    log_info "Copied into container: ${destination_path}"
    pause
}

###############################################################################
# Container lifecycle
###############################################################################

restart_container() {
    if confirm "Restart ${SELECTED_CONTAINER}?"; then
        docker restart "${SELECTED_CONTAINER}"
        log_info "Container restarted."
    fi

    pause
}

stop_container() {
    if confirm "Stop ${SELECTED_CONTAINER}?"; then
        docker stop "${SELECTED_CONTAINER}"
        log_info "Container stopped."
    fi

    pause
}

start_container() {
    if container_running "${SELECTED_CONTAINER}"; then
        log_info "Container is already running."
    else
        docker start "${SELECTED_CONTAINER}"
        log_info "Container started."
    fi

    pause
}

remove_container() {
    if confirm "Permanently remove container ${SELECTED_CONTAINER}?"; then
        docker rm --force "${SELECTED_CONTAINER}"
        log_info "Container removed."

        SELECTED_CONTAINER=""
        SELECTED_CONTAINER_ID=""
    fi

    pause
}

###############################################################################
# Export diagnostics
###############################################################################

export_diagnostics() {
    local timestamp
    local output_file

    timestamp="$(date '+%Y%m%d_%H%M%S')"
    output_file="./${SELECTED_CONTAINER}_diagnostics_${timestamp}.txt"

    log_info "Writing diagnostics to ${output_file}"

    {
        printf 'Docker Container Diagnostics\n'
        printf 'Generated: %s\n' "$(date --iso-8601=seconds)"
        printf 'Container: %s\n\n' "${SELECTED_CONTAINER}"

        printf '=== docker inspect ===\n'
        docker inspect "${SELECTED_CONTAINER}"

        printf '\n=== docker stats ===\n'
        docker stats --no-stream "${SELECTED_CONTAINER}"

        printf '\n=== docker top ===\n'
        docker top "${SELECTED_CONTAINER}" 2>&1 || true

        printf '\n=== docker port ===\n'
        docker port "${SELECTED_CONTAINER}" 2>&1 || true

        printf '\n=== docker diff ===\n'
        docker diff "${SELECTED_CONTAINER}" 2>&1 || true

        printf '\n=== last 500 log lines ===\n'
        docker logs \
            --timestamps \
            --tail 500 \
            "${SELECTED_CONTAINER}" 2>&1 || true
    } > "${output_file}"

    log_info "Diagnostics saved: ${output_file}"
    pause
}

###############################################################################
# Menus
###############################################################################

logs_menu() {
    local choice

    while true; do
        print_header
        print_selected_container

        printf '%sLogs menu%s\n\n' \
            "${COLOR_BOLD}" \
            "${COLOR_RESET}"

        cat <<'MENU'
1) Show last N log lines
2) Follow live logs
3) Show logs since a time
4) Search recent logs
5) Back
MENU

        printf '\n'
        read -r -p "Choose an option: " choice

        case "${choice}" in
            1)
                show_logs
                ;;
            2)
                follow_logs
                ;;
            3)
                show_logs_since
                ;;
            4)
                search_logs
                ;;
            5)
                return
                ;;
            *)
                log_error "Invalid option."
                pause
                ;;
        esac
    done
}

inspection_menu() {
    local choice

    while true; do
        print_header
        print_selected_container

        printf '%sInspection menu%s\n\n' \
            "${COLOR_BOLD}" \
            "${COLOR_RESET}"

        cat <<'MENU'
1) Container summary
2) Full docker inspect output
3) Live resource statistics
4) One-time resource statistics
5) Running processes
6) Port mappings
7) Environment variables
8) Mounts and volumes
9) Network information
10) Health information
11) Filesystem changes
12) Export diagnostics report
13) Back
MENU

        printf '\n'
        read -r -p "Choose an option: " choice

        case "${choice}" in
            1)
                show_summary
                ;;
            2)
                show_full_inspect
                ;;
            3)
                show_stats
                ;;
            4)
                show_one_time_stats
                ;;
            5)
                show_processes
                ;;
            6)
                show_ports
                ;;
            7)
                show_environment
                ;;
            8)
                show_mounts
                ;;
            9)
                show_networks
                ;;
            10)
                show_health
                ;;
            11)
                show_changes
                ;;
            12)
                export_diagnostics
                ;;
            13)
                return
                ;;
            *)
                log_error "Invalid option."
                pause
                ;;
        esac
    done
}

file_menu() {
    local choice

    while true; do
        print_header
        print_selected_container

        printf '%sFile transfer menu%s\n\n' \
            "${COLOR_BOLD}" \
            "${COLOR_RESET}"

        cat <<'MENU'
1) Copy file or directory from container
2) Copy file or directory into container
3) Back
MENU

        printf '\n'
        read -r -p "Choose an option: " choice

        case "${choice}" in
            1)
                copy_from_container
                ;;
            2)
                copy_to_container
                ;;
            3)
                return
                ;;
            *)
                log_error "Invalid option."
                pause
                ;;
        esac
    done
}

lifecycle_menu() {
    local choice

    while true; do
        print_header
        print_selected_container

        printf '%sContainer lifecycle menu%s\n\n' \
            "${COLOR_BOLD}" \
            "${COLOR_RESET}"

        cat <<'MENU'
1) Start container
2) Restart container
3) Stop container
4) Remove container
5) Back
MENU

        printf '\n'
        read -r -p "Choose an option: " choice

        case "${choice}" in
            1)
                start_container
                ;;
            2)
                restart_container
                ;;
            3)
                stop_container
                ;;
            4)
                remove_container

                if [[ -z "${SELECTED_CONTAINER}" ]]; then
                    return
                fi
                ;;
            5)
                return
                ;;
            *)
                log_error "Invalid option."
                pause
                ;;
        esac
    done
}

container_menu() {
    local choice

    while [[ -n "${SELECTED_CONTAINER}" ]]; do
        if ! container_exists "${SELECTED_CONTAINER}"; then
            log_warn "The selected container no longer exists."
            SELECTED_CONTAINER=""
            SELECTED_CONTAINER_ID=""
            pause
            return
        fi

        print_header
        print_selected_container

        cat <<'MENU'
1) Open shell inside container
2) Run a custom command
3) Logs
4) Inspect container
5) Copy files
6) Start, restart, stop, or remove
7) Select another running container
8) Select from all containers
9) Refresh
0) Exit
MENU

        printf '\n'
        read -r -p "Choose an option: " choice

        case "${choice}" in
            1)
                open_shell
                ;;
            2)
                run_command
                ;;
            3)
                logs_menu
                ;;
            4)
                inspection_menu
                ;;
            5)
                file_menu
                ;;
            6)
                lifecycle_menu
                ;;
            7)
                if select_container false; then
                    continue
                fi
                ;;
            8)
                if select_container true; then
                    continue
                fi
                ;;
            9)
                continue
                ;;
            0)
                exit 0
                ;;
            *)
                log_error "Invalid option."
                pause
                ;;
        esac
    done
}

###############################################################################
# Main
###############################################################################

while true; do
    if select_container false; then
        container_menu
    else
        printf '\n'
        read -r -p \
            "Show stopped containers too? [y/N]: " \
            show_all

        case "${show_all,,}" in
            y|yes)
                if select_container true; then
                    container_menu
                fi
                ;;
            *)
                exit 0
                ;;
        esac
    fi
done