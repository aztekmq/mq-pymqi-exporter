
ARG BASE_IMAGE=mq-local-monitoring:latest
FROM ${BASE_IMAGE}

USER root

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG PYTHON_VERSION=3.11.9

ENV MQ_INSTALLATION_PATH=/opt/mqm \
    VIRTUAL_ENV=/opt/mq-exporter-venv \
    LD_LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib:/opt/python311/lib \
    PATH=/opt/mq-exporter-venv/bin:/opt/python311/bin:/opt/mqm/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

###############################################################################
# Install all compiler and Python build requirements inside the image.
#
# Only packages available from the IBM MQ image's enabled UBI repositories are
# used here.
###############################################################################

RUN set -Eeuo pipefail; \
    if command -v microdnf >/dev/null 2>&1; then \
        microdnf install -y \
            gcc \
            gcc-c++ \
            make \
            curl \
            tar \
            gzip \
            findutils \
            openssl-devel \
            zlib-devel \
            libffi-devel \
        && microdnf clean all; \
    elif command -v dnf >/dev/null 2>&1; then \
        dnf install -y \
            gcc \
            gcc-c++ \
            make \
            curl \
            tar \
            gzip \
            findutils \
            openssl-devel \
            zlib-devel \
            libffi-devel \
        && dnf clean all; \
    elif command -v yum >/dev/null 2>&1; then \
        yum install -y \
            gcc \
            gcc-c++ \
            make \
            curl \
            tar \
            gzip \
            findutils \
            openssl-devel \
            zlib-devel \
            libffi-devel \
        && yum clean all; \
    else \
        echo "[ERROR] No supported package manager found." >&2; \
        exit 1; \
    fi

###############################################################################
# Build Python entirely inside the image.
###############################################################################

RUN set -Eeuo pipefail; \
    cd /tmp; \
    curl \
        --fail \
        --location \
        --retry 3 \
        --retry-delay 2 \
        --output "Python-${PYTHON_VERSION}.tgz" \
        "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"; \
    tar -xzf "Python-${PYTHON_VERSION}.tgz"; \
    cd "Python-${PYTHON_VERSION}"; \
    ./configure \
        --prefix=/opt/python311 \
        --enable-shared \
        --with-ensurepip=install \
        --without-readline; \
    make -j"$(nproc)"; \
    make install; \
    printf '/opt/python311/lib\n' \
        > /etc/ld.so.conf.d/python311.conf; \
    ldconfig; \
    /opt/python311/bin/python3.11 --version; \
    /opt/python311/bin/python3.11 -m pip --version; \
    rm -rf \
        "/tmp/Python-${PYTHON_VERSION}" \
        "/tmp/Python-${PYTHON_VERSION}.tgz"

###############################################################################
# Copy the local IBM MQ redistributable client and SDK into the image.
#
# mqredist points directly at:
#
# ibm_mq_redist_packages/10.0.0.0-IBM-MQC-Redist-LinuxX64
###############################################################################

COPY --from=mqredist / /opt/mqm/

RUN set -Eeuo pipefail; \
    test -f /opt/mqm/inc/cmqc.h; \
    test -e /opt/mqm/lib64/libmqic_r.so; \
    printf '/opt/mqm/lib64\n/opt/mqm/lib\n' \
        > /etc/ld.so.conf.d/ibm-mq.conf; \
    ldconfig; \
    echo "[INFO] IBM MQ header: /opt/mqm/inc/cmqc.h"; \
    echo "[INFO] IBM MQ library: /opt/mqm/lib64/libmqic_r.so"

###############################################################################
# Create the exporter virtual environment inside the image.
###############################################################################

RUN set -Eeuo pipefail; \
    /opt/python311/bin/python3.11 -m venv "${VIRTUAL_ENV}"; \
    "${VIRTUAL_ENV}/bin/python" -m pip install \
        --upgrade \
        pip \
        setuptools \
        wheel; \
    "${VIRTUAL_ENV}/bin/python" --version; \
    "${VIRTUAL_ENV}/bin/python" -m pip --version

###############################################################################
# Copy only the dependency definition first for Docker layer caching.
###############################################################################

WORKDIR /app

COPY requirements.txt /app/requirements.txt

###############################################################################
# Build pyMQI and all Python dependencies inside the image.
###############################################################################

RUN set -Eeuo pipefail; \
    export MQ_INSTALLATION_PATH=/opt/mqm; \
    export C_INCLUDE_PATH=/opt/mqm/inc; \
    export CPATH=/opt/mqm/inc; \
    export CPLUS_INCLUDE_PATH=/opt/mqm/inc; \
    export LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib; \
    export LD_LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib:/opt/python311/lib; \
    "${VIRTUAL_ENV}/bin/python" -m pip install \
        --no-cache-dir \
        --verbose \
        -r /app/requirements.txt; \
    "${VIRTUAL_ENV}/bin/python" -c \
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

RUN set -Eeuo pipefail; \
    export MQ_INSTALLATION_PATH=/opt/mqm; \
    export C_INCLUDE_PATH=/opt/mqm/inc; \
    export CPATH=/opt/mqm/inc; \
    export CPLUS_INCLUDE_PATH=/opt/mqm/inc; \
    export LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib; \
    export LD_LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib:/opt/python311/lib; \
    "${VIRTUAL_ENV}/bin/python" -m pip install \
        --no-cache-dir \
        /app; \
    "${VIRTUAL_ENV}/bin/python" -c \
        'import pymqi; print("[INFO] pyMQI installed:", pymqi.__file__)'; \
    "${VIRTUAL_ENV}/bin/python" -c \
        'import mq_exporter; print("[INFO] exporter installed:", mq_exporter.__file__)'

###############################################################################
# Install runtime entrypoint.
###############################################################################

COPY docker_build/mq-pymqi-exporter/docker-entrypoint.sh \
    /usr/local/bin/mq-pymqi-exporter-entrypoint

RUN chmod 0755 /usr/local/bin/mq-pymqi-exporter-entrypoint \
    && chown -R 1001:0 /app "${VIRTUAL_ENV}" \
    && chmod -R g=u /app "${VIRTUAL_ENV}"

USER 1001

EXPOSE 9157

ENV EXPORTER_CONFIG=/app/examples/exporter.yaml \
    EXPORTER_PORT=9157

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=30s \
    --retries=3 \
    CMD /opt/mq-exporter-venv/bin/python -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9157/status', timeout=3)" \
        || exit 1

ENTRYPOINT ["/usr/local/bin/mq-pymqi-exporter-entrypoint"]
