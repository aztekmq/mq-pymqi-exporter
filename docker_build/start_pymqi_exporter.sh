#!/usr/bin/env bash
# =============================================================================
# Script Name : start_pymqi_exporter.sh
# Description : Build mq-pymqi-exporter entirely inside a Docker image and run
#               the exporter inside the resulting container.
#
# Host requirements:
#   - Docker with BuildKit support
#
# Everything else is built inside the container image:
#   - GCC and compiler tools
#   - Python 3.11
#   - IBM MQ redistributable client and SDK
#   - pyMQI
#   - exporter dependencies
#   - mq-pymqi-exporter package
#
# Expected repository layout:
#
# mq-pymqi-exporter/
# ├── requirements.txt
# ├── pyproject.toml or setup.py
# ├── src/
# ├── examples/
# │   ├── exporter.yaml
# │   └── qmgrs/
# └── docker_build/
#     ├── start_pymqi_exporter.sh
#     ├── mq-monitoring/
#     │   ├── Dockerfile
#     │   └── monitoring-auth.mqsc
#     └── ibm_mq_redist_packages/
#         └── 10.0.0.0-IBM-MQC-Redist-LinuxX64/
#             ├── inc/cmqc.h
#             ├── lib64/libmqic_r.so
#             ├── bin/
#             └── ...
#
# Usage:
#
#   cd docker_build
#   chmod +x start_pymqi_exporter.sh
#   ./start_pymqi_exporter.sh
#
# Optional environment variables:
#
#   BASE_IMAGE=mq-local-monitoring:latest
#   EXPORTER_IMAGE=mq-pymqi-exporter:latest
#   CONTAINER_NAME=mq-pymqi-exporter
#   EXPORTER_PORT=9157
#   PYTHON_VERSION=3.11.9
#   MQ_QM1_PASSWORD=passw0rd
#   DOCKER_NETWORK=docker_build_default
#   REBUILD_BASE=false
#   NO_CACHE=false
# =============================================================================

set -Eeuo pipefail

###############################################################################
# Paths
###############################################################################

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

BASE_IMAGE_CONTEXT="${SCRIPT_DIR}/mq-monitoring"
BASE_DOCKERFILE="${BASE_IMAGE_CONTEXT}/Dockerfile"

MQ_REDIST_DIR="${SCRIPT_DIR}/ibm_mq_redist_packages/10.0.0.0-IBM-MQC-Redist-LinuxX64"

GENERATED_DIR="${SCRIPT_DIR}/mq-pymqi-exporter"
GENERATED_DOCKERFILE="${GENERATED_DIR}/Dockerfile"
GENERATED_ENTRYPOINT="${GENERATED_DIR}/docker-entrypoint.sh"
BUILD_CONTEXT_DIR="${GENERATED_DIR}/build-context"

###############################################################################
# Settings
###############################################################################

BASE_IMAGE="${BASE_IMAGE:-mq-local-monitoring:latest}"
EXPORTER_IMAGE="${EXPORTER_IMAGE:-mq-pymqi-exporter:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-mq-pymqi-exporter}"

EXPORTER_PORT="${EXPORTER_PORT:-9157}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11.9}"

MQ_QM1_PASSWORD="${MQ_QM1_PASSWORD:-passw0rd}"

DOCKER_NETWORK="${DOCKER_NETWORK:-docker_build_default}"

REBUILD_BASE="${REBUILD_BASE:-false}"
NO_CACHE="${NO_CACHE:-false}"

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

on_exit() {
    local exit_code=$?

    if (( exit_code != 0 )); then
        log_error "Operation failed with exit code ${exit_code}."
    fi

    exit "${exit_code}"
}

trap on_exit EXIT

###############################################################################
# Validate host files
###############################################################################

require_command docker

[[ -f "${BASE_DOCKERFILE}" ]] ||
    die "IBM MQ base Dockerfile not found: ${BASE_DOCKERFILE}"

[[ -f "${MQ_REDIST_DIR}/inc/cmqc.h" ]] ||
    die "IBM MQ header not found: ${MQ_REDIST_DIR}/inc/cmqc.h"

[[ -e "${MQ_REDIST_DIR}/lib64/libmqic_r.so" ]] ||
    die "IBM MQ library not found: ${MQ_REDIST_DIR}/lib64/libmqic_r.so"

[[ -f "${REPO_ROOT}/requirements.txt" ]] ||
    die "requirements.txt not found: ${REPO_ROOT}/requirements.txt"

[[ -d "${REPO_ROOT}/src" ]] ||
    die "Exporter source directory not found: ${REPO_ROOT}/src"

[[ -f "${REPO_ROOT}/examples/exporter.yaml" ]] ||
    die "Exporter config not found: ${REPO_ROOT}/examples/exporter.yaml"

if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]] &&
   [[ ! -f "${REPO_ROOT}/setup.py" ]]; then
    die "Neither pyproject.toml nor setup.py was found in ${REPO_ROOT}"
fi

log_info "Repository root: ${REPO_ROOT}"
log_info "IBM MQ SDK root: ${MQ_REDIST_DIR}"
log_info "IBM MQ header: ${MQ_REDIST_DIR}/inc/cmqc.h"
log_info "IBM MQ library: ${MQ_REDIST_DIR}/lib64/libmqic_r.so"

export DOCKER_BUILDKIT=1

###############################################################################
# Reuse or rebuild existing IBM MQ base image
###############################################################################

if docker image inspect "${BASE_IMAGE}" >/dev/null 2>&1; then
    if [[ "${REBUILD_BASE,,}" == "true" ]]; then
        log_info "Rebuilding IBM MQ base image: ${BASE_IMAGE}"

        docker build \
            --pull=false \
            --file "${BASE_DOCKERFILE}" \
            --tag "${BASE_IMAGE}" \
            "${BASE_IMAGE_CONTEXT}"
    else
        log_info "Using existing local IBM MQ base image: ${BASE_IMAGE}"
    fi
else
    log_warn "Base image does not exist locally: ${BASE_IMAGE}"
    log_info "Attempting to build the base image..."

    docker build \
        --pull=false \
        --file "${BASE_DOCKERFILE}" \
        --tag "${BASE_IMAGE}" \
        "${BASE_IMAGE_CONTEXT}" ||
    {
        log_error "Unable to build the IBM MQ base image."
        log_error "Docker Hub may be unavailable and the parent IBM MQ image may not exist locally."
        exit 1
    }
fi

###############################################################################
# Generate Docker build files
###############################################################################

mkdir -p "${GENERATED_DIR}"

cat > "${GENERATED_ENTRYPOINT}" <<'ENTRYPOINT_EOF'
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
ENTRYPOINT_EOF

chmod 0755 "${GENERATED_ENTRYPOINT}"

###############################################################################
# Generate Dockerfile
###############################################################################

cat > "${GENERATED_DOCKERFILE}" <<EOF

ARG BASE_IMAGE=${BASE_IMAGE}
FROM \${BASE_IMAGE}

USER root

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG PYTHON_VERSION=${PYTHON_VERSION}

ENV MQ_INSTALLATION_PATH=/opt/mqm \\
    VIRTUAL_ENV=/opt/mq-exporter-venv \\
    LD_LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib:/opt/python311/lib \\
    PATH=/opt/mq-exporter-venv/bin:/opt/python311/bin:/opt/mqm/bin:\${PATH} \\
    PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1

###############################################################################
# Install all compiler and Python build requirements inside the image.
#
# Only packages available from the IBM MQ image's enabled UBI repositories are
# used here.
###############################################################################

RUN set -Eeuo pipefail; \\
    if command -v microdnf >/dev/null 2>&1; then \\
        microdnf install -y \\
            gcc \\
            gcc-c++ \\
            make \\
            curl \\
            tar \\
            gzip \\
            findutils \\
            openssl-devel \\
            zlib-devel \\
            libffi-devel \\
        && microdnf clean all; \\
    elif command -v dnf >/dev/null 2>&1; then \\
        dnf install -y \\
            gcc \\
            gcc-c++ \\
            make \\
            curl \\
            tar \\
            gzip \\
            findutils \\
            openssl-devel \\
            zlib-devel \\
            libffi-devel \\
        && dnf clean all; \\
    elif command -v yum >/dev/null 2>&1; then \\
        yum install -y \\
            gcc \\
            gcc-c++ \\
            make \\
            curl \\
            tar \\
            gzip \\
            findutils \\
            openssl-devel \\
            zlib-devel \\
            libffi-devel \\
        && yum clean all; \\
    else \\
        echo "[ERROR] No supported package manager found." >&2; \\
        exit 1; \\
    fi

###############################################################################
# Build Python entirely inside the image.
###############################################################################

RUN set -Eeuo pipefail; \\
    cd /tmp; \\
    curl \\
        --fail \\
        --location \\
        --retry 3 \\
        --retry-delay 2 \\
        --output "Python-\${PYTHON_VERSION}.tgz" \\
        "https://www.python.org/ftp/python/\${PYTHON_VERSION}/Python-\${PYTHON_VERSION}.tgz"; \\
    tar -xzf "Python-\${PYTHON_VERSION}.tgz"; \\
    cd "Python-\${PYTHON_VERSION}"; \\
    ./configure \\
        --prefix=/opt/python311 \\
        --enable-shared \\
        --with-ensurepip=install \\
        --without-readline; \\
    make -j"\$(nproc)"; \\
    make install; \\
    printf '/opt/python311/lib\\n' \\
        > /etc/ld.so.conf.d/python311.conf; \\
    ldconfig; \\
    /opt/python311/bin/python3.11 --version; \\
    /opt/python311/bin/python3.11 -m pip --version; \\
    rm -rf \\
        "/tmp/Python-\${PYTHON_VERSION}" \\
        "/tmp/Python-\${PYTHON_VERSION}.tgz"

###############################################################################
# Copy the local IBM MQ redistributable client and SDK into the image.
#
# mqredist points directly at:
#
# ibm_mq_redist_packages/10.0.0.0-IBM-MQC-Redist-LinuxX64
###############################################################################

COPY --from=mqredist / /opt/mqm/

RUN set -Eeuo pipefail; \\
    test -f /opt/mqm/inc/cmqc.h; \\
    test -e /opt/mqm/lib64/libmqic_r.so; \\
    printf '/opt/mqm/lib64\\n/opt/mqm/lib\\n' \\
        > /etc/ld.so.conf.d/ibm-mq.conf; \\
    ldconfig; \\
    echo "[INFO] IBM MQ header: /opt/mqm/inc/cmqc.h"; \\
    echo "[INFO] IBM MQ library: /opt/mqm/lib64/libmqic_r.so"

###############################################################################
# Create the exporter virtual environment inside the image.
###############################################################################

RUN set -Eeuo pipefail; \\
    /opt/python311/bin/python3.11 -m venv "\${VIRTUAL_ENV}"; \\
    "\${VIRTUAL_ENV}/bin/python" -m pip install \\
        --upgrade \\
        pip \\
        setuptools \\
        wheel; \\
    "\${VIRTUAL_ENV}/bin/python" --version; \\
    "\${VIRTUAL_ENV}/bin/python" -m pip --version

###############################################################################
# Copy only the dependency definition first for Docker layer caching.
###############################################################################

WORKDIR /app

COPY requirements.txt /app/requirements.txt

###############################################################################
# Build pyMQI and all Python dependencies inside the image.
###############################################################################

RUN set -Eeuo pipefail; \\
    export MQ_INSTALLATION_PATH=/opt/mqm; \\
    export C_INCLUDE_PATH=/opt/mqm/inc; \\
    export CPATH=/opt/mqm/inc; \\
    export CPLUS_INCLUDE_PATH=/opt/mqm/inc; \\
    export LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib; \\
    export LD_LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib:/opt/python311/lib; \\
    "\${VIRTUAL_ENV}/bin/python" -m pip install \\
        --no-cache-dir \\
        --verbose \\
        -r /app/requirements.txt; \\
    "\${VIRTUAL_ENV}/bin/python" -c \\
        'import pymqi; print("[INFO] pyMQI built inside container:", pymqi.__file__)'

###############################################################################
# Copy the clean exporter build context into the image.
#
# The host script creates this context with only the files required to build
# the exporter. IBM MQ runtime data directories are never sent to Docker.
###############################################################################

COPY . /app/

###############################################################################
# Build and install the exporter package inside the image.
###############################################################################

RUN set -Eeuo pipefail; \\
    export MQ_INSTALLATION_PATH=/opt/mqm; \\
    export C_INCLUDE_PATH=/opt/mqm/inc; \\
    export CPATH=/opt/mqm/inc; \\
    export CPLUS_INCLUDE_PATH=/opt/mqm/inc; \\
    export LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib; \\
    export LD_LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib:/opt/python311/lib; \\
    "\${VIRTUAL_ENV}/bin/python" -m pip install \\
        --no-cache-dir \\
        /app; \\
    "\${VIRTUAL_ENV}/bin/python" -c \\
        'import pymqi; print("[INFO] pyMQI installed:", pymqi.__file__)'; \\
    "\${VIRTUAL_ENV}/bin/python" -c \\
        'import mq_exporter; print("[INFO] exporter installed:", mq_exporter.__file__)'

###############################################################################
# Install runtime entrypoint.
###############################################################################

COPY docker_build/mq-pymqi-exporter/docker-entrypoint.sh \\
    /usr/local/bin/mq-pymqi-exporter-entrypoint

RUN chmod 0755 /usr/local/bin/mq-pymqi-exporter-entrypoint \\
    && chown -R 1001:0 /app "\${VIRTUAL_ENV}" \\
    && chmod -R g=u /app "\${VIRTUAL_ENV}"

USER 1001

EXPOSE ${EXPORTER_PORT}

ENV EXPORTER_CONFIG=/app/examples/exporter.yaml \\
    EXPORTER_PORT=${EXPORTER_PORT}

HEALTHCHECK \\
    --interval=30s \\
    --timeout=5s \\
    --start-period=30s \\
    --retries=3 \\
    CMD /opt/mq-exporter-venv/bin/python -c \\
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${EXPORTER_PORT}/status', timeout=3)" \\
        || exit 1

ENTRYPOINT ["/usr/local/bin/mq-pymqi-exporter-entrypoint"]
EOF

###############################################################################
# Prepare a clean Docker build context
#
# Do not use the repository root as the Docker build context. The repository
# contains IBM MQ runtime data under docker_build/data, and those files may be
# owned by the MQ container and unreadable by the current host user.
###############################################################################

log_info "Preparing clean Docker build context: ${BUILD_CONTEXT_DIR}"

rm -rf -- "${BUILD_CONTEXT_DIR}"

mkdir -p \
    "${BUILD_CONTEXT_DIR}/src" \
    "${BUILD_CONTEXT_DIR}/examples" \
    "${BUILD_CONTEXT_DIR}/docker_build/mq-pymqi-exporter"

cp -- "${REPO_ROOT}/requirements.txt" \
    "${BUILD_CONTEXT_DIR}/requirements.txt"

cp -a -- "${REPO_ROOT}/src/." \
    "${BUILD_CONTEXT_DIR}/src/"

cp -a -- "${REPO_ROOT}/examples/." \
    "${BUILD_CONTEXT_DIR}/examples/"

cp -- "${GENERATED_ENTRYPOINT}" \
    "${BUILD_CONTEXT_DIR}/docker_build/mq-pymqi-exporter/docker-entrypoint.sh"

for packaging_file in \
    pyproject.toml \
    setup.py \
    setup.cfg \
    MANIFEST.in \
    README \
    README.md \
    README.rst \
    LICENSE \
    LICENSE.md \
    LICENSE.txt
do
    if [[ -f "${REPO_ROOT}/${packaging_file}" ]]; then
        cp -- "${REPO_ROOT}/${packaging_file}" \
            "${BUILD_CONTEXT_DIR}/${packaging_file}"
    fi
done

if [[ ! -f "${BUILD_CONTEXT_DIR}/pyproject.toml" ]] &&
   [[ ! -f "${BUILD_CONTEXT_DIR}/setup.py" ]]; then
    die "The clean build context contains neither pyproject.toml nor setup.py."
fi

log_info "Clean build context contents:"
find "${BUILD_CONTEXT_DIR}" \
    -maxdepth 4 \
    -type f \
    -printf '  %P\n' \
    | sort

###############################################################################
# Build exporter image
###############################################################################

BUILD_ARGS=(
    --pull=false
    --file "${GENERATED_DOCKERFILE}"
    --tag "${EXPORTER_IMAGE}"
    --build-arg "BASE_IMAGE=${BASE_IMAGE}"
    --build-arg "PYTHON_VERSION=${PYTHON_VERSION}"
    --build-context "mqredist=${MQ_REDIST_DIR}"
    --progress plain
)

if [[ "${NO_CACHE,,}" == "true" ]]; then
    BUILD_ARGS+=(--no-cache)
fi

log_info "Building exporter entirely inside Docker"
log_info "Exporter image: ${EXPORTER_IMAGE}"
log_info "Python version: ${PYTHON_VERSION}"
log_info "Dockerfile: ${GENERATED_DOCKERFILE}"
log_info "Build context: ${BUILD_CONTEXT_DIR}"

docker build \
    "${BUILD_ARGS[@]}" \
    "${BUILD_CONTEXT_DIR}"

###############################################################################
# Remove previous exporter container
###############################################################################

if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    log_info "Removing existing exporter container: ${CONTAINER_NAME}"
    docker rm --force "${CONTAINER_NAME}" >/dev/null
fi

###############################################################################
# Configure network
###############################################################################

NETWORK_ARGS=()

if [[ -n "${DOCKER_NETWORK}" ]]; then
    if docker network inspect "${DOCKER_NETWORK}" >/dev/null 2>&1; then
        log_info "Using Docker network: ${DOCKER_NETWORK}"
        NETWORK_ARGS=(--network "${DOCKER_NETWORK}")
    else
        log_warn "Docker network not found: ${DOCKER_NETWORK}"
        log_warn "Using Docker's default bridge network."
    fi
fi

###############################################################################
# Start exporter inside the completed container
###############################################################################

log_info "Starting exporter container: ${CONTAINER_NAME}"

docker run \
    --detach \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    --publish "127.0.0.1:${EXPORTER_PORT}:${EXPORTER_PORT}" \
    --env "MQ_QM1_PASSWORD=${MQ_QM1_PASSWORD}" \
    --env "EXPORTER_CONFIG=/app/examples/exporter.yaml" \
    --env "EXPORTER_PORT=${EXPORTER_PORT}" \
    --add-host "host.docker.internal:host-gateway" \
    --volume "${REPO_ROOT}/examples:/app/examples:ro" \
    "${NETWORK_ARGS[@]}" \
    "${EXPORTER_IMAGE}"

###############################################################################
# Validate runtime
###############################################################################

sleep 3

CONTAINER_STATE="$(
    docker inspect \
        --format '{{.State.Status}}' \
        "${CONTAINER_NAME}"
)"

if [[ "${CONTAINER_STATE}" != "running" ]]; then
    log_error "Exporter container is not running."
    docker logs "${CONTAINER_NAME}" || true
    exit 1
fi

log_info "Verifying Python inside exporter container..."

docker exec "${CONTAINER_NAME}" \
    /opt/mq-exporter-venv/bin/python --version

log_info "Verifying pyMQI inside exporter container..."

docker exec "${CONTAINER_NAME}" \
    /opt/mq-exporter-venv/bin/python \
    -c 'import pymqi; print(pymqi.__file__)'

log_info "Verifying exporter inside exporter container..."

docker exec "${CONTAINER_NAME}" \
    /opt/mq-exporter-venv/bin/python \
    -c 'import mq_exporter; print(mq_exporter.__file__)'

###############################################################################
# Summary
###############################################################################

printf '\n'
printf 'Deployment Summary\n'
printf '%-28s %s\n' "Base image:" "${BASE_IMAGE}"
printf '%-28s %s\n' "Exporter image:" "${EXPORTER_IMAGE}"
printf '%-28s %s\n' "Container:" "${CONTAINER_NAME}"
printf '%-28s %s\n' "Container state:" "${CONTAINER_STATE}"
printf '%-28s %s\n' "Python:" "${PYTHON_VERSION}"
printf '%-28s %s\n' "MQ SDK:" "${MQ_REDIST_DIR}"
printf '%-28s %s\n' "Docker network:" "${DOCKER_NETWORK}"
printf '%-28s %s\n' "Exporter:" "http://localhost:${EXPORTER_PORT}/"
printf '%-28s %s\n' "Info:" "http://localhost:${EXPORTER_PORT}/info"
printf '%-28s %s\n' "Status:" "http://localhost:${EXPORTER_PORT}/status"
printf '%-28s %s\n' "Metrics:" "http://localhost:${EXPORTER_PORT}/metrics"
printf '\n'

log_info "Recent exporter logs:"
docker logs --tail 50 "${CONTAINER_NAME}"

printf '\n'
log_info "Useful commands:"
printf '  docker logs -f %s\n' "${CONTAINER_NAME}"
printf '  docker exec -it %s bash\n' "${CONTAINER_NAME}"
printf '  curl http://localhost:%s/status\n' "${EXPORTER_PORT}"
printf '  curl http://localhost:%s/metrics\n' "${EXPORTER_PORT}"

trap - EXIT
