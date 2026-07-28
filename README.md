# mq-pymqi-exporter

Prometheus exporter for IBM MQ, implemented in Python with pyMQI and the IBM MQ
client tools. MQ collection runs in the background; HTTP requests read a cached
Prometheus registry and do not wait for a queue manager.

The repository also contains a complete local Docker lab: IBM MQ queue managers,
the exporter, Prometheus, Grafana, dashboards, and Bash helpers for operating
each component.

## What it collects

Metric names use the `ibmmq_` prefix. The exact set exposed at any moment depends
on the enabled collectors, matching objects, MQ version, generated MQ traffic,
and whether accounting/statistics intervals have completed.

| Area | Source |
| --- | --- |
| Exporter health, poll duration, success, and errors | Exporter runtime |
| Queue-manager configuration and status | pyMQI PCF inquiries |
| Queue configuration, depth, open handles, ages, rates, and status | pyMQI PCF inquiries and MQ monitoring data |
| Channel configuration and status | pyMQI PCF inquiries |
| Topic configuration/status | pyMQI PCF inquiries |
| Accounting and statistics records | IBM MQ administration queues |
| Activity trace records | IBM MQ activity queues |
| Queue-manager, performance, channel, command, configuration, logger, and pub/sub events | IBM MQ event queues |
| CPU, disk, and log metrics | Client-mode `amqsruac` |
| STATMQI totals and rates | Client-mode `amqsruac` |
| STATQ per-queue OPENCLOSE, INQSET, PUT, GET, and GENERAL metrics | Client-mode `amqsruac` |
| STATAPP metrics for observed applications | Client-mode `amqsruac` |
| `$SYS/MQ/INFO/QMGR/...` monitoring publications | Dynamic subscription to `SYSTEM.ADMIN.TOPIC` |

`amqsruac` is the client-capable program shipped with IBM MQ. It is intentionally
used here instead of `amqsrua`, which is a bindings-mode tool.

Administration/event queue collectors consume messages. If another application
also drains those queues, records are divided between consumers rather than
duplicated.

## Architecture

```text
IBM MQ
  ├─ PCF command/reply ───────────────┐
  ├─ admin and event queues ─────────┤
  ├─ SYSTEM.ADMIN.TOPIC ─────────────┤
  └─ amqsruac client connection ─────┤
                                     v
                            background collector
                                     |
                              cached registry
                                     |
                  /metrics   /status   /info   /
```

Each enabled queue manager has its own polling interval. A bounded worker pool
collects concurrently, while the HTTP server remains responsive. Failed polls
leave the last successful MQ samples in the cache and update exporter health and
status information.

## Requirements

For the Docker lab:

- Linux or WSL with Bash
- Docker Engine with Compose v2 and BuildKit
- `ss` from `iproute2` for port checks
- `sudo` for the MQ data-directory ownership operations
- The IBM MQ redistributable client/SDK at
  `docker_build/ibm_mq_redist_packages/10.0.0.0-IBM-MQC-Redist-LinuxX64`

For a source installation:

- Python 3.10 or newer
- IBM MQ client libraries and headers compatible with pyMQI
- `amqsruac` when CPU, disk, log, STATMQI, or STATAPP data is required

## Quick start: complete Docker lab

Run the stack helpers from `docker_build`; the MQ, Prometheus, and Grafana start
scripts create files relative to the current directory.

```bash
cd docker_build

# Build and start one queue manager.
./start_mq.sh 1

# Build and start the exporter on the MQ Compose network.
./start_pymqi_exporter.sh

# Optional monitoring UI stack.
./start_prometheus.sh
./start_grafana.sh
```

Open:

- Exporter metrics: <http://localhost:9157/metrics>
- Exporter status: <http://localhost:9157/status>
- Prometheus: <http://localhost:9091/>
- Grafana: <http://localhost:3000/> (`admin` / `admin` by default)
- QM1 web console: <https://localhost:9444/>

> **Data-loss warning:** every invocation of `start_mq.sh` brings down the
> existing MQ Compose stack and deletes `docker_build/data` before recreating
> it. Do not use that helper to restart queue managers whose data must survive.

### Docker networking

The address depends on where the MQ client runs:

| Client location | QM1 connection name |
| --- | --- |
| Exporter container on `docker_build_default` | `qm1(1414)` |
| Process running directly on the host | `localhost(1415)` |

Containers must use the MQ container/service name and its internal port. Inside
the exporter container, `localhost` means the exporter itself—not QM1.

For queue manager `N`, `start_mq.sh` creates container `qmN` and maps these host
ports:

- MQ listener: `1414 + N`
- Web console: `9443 + N`
- REST administration: `9449 + N`

The included QM1 example therefore correctly uses `qm1(1414)` because the
exporter runs in a separate container on the same network.

## Configuration

The top-level file is [examples/exporter.yaml](examples/exporter.yaml). It
defines the HTTP server, scheduler, defaults, and directory containing one YAML
file per queue manager.

```yaml
server:
  host: 0.0.0.0
  port: 9157
  metrics_path: /metrics

worker_pool:
  max_threads: 50
  scheduler_tick_seconds: 1.0

logging:
  level: INFO

default_poll_interval: 30s
default_timeout: 20s
qmgr_directory: qmgrs
```

Durations support `ms`, `s`, `m`, and `h`. Worker threads are hard-capped at 50.

The included [QM1 configuration](examples/qmgrs/local-qm1.yaml) enables the
available collector families:

```yaml
name: QM1
enabled: true
poll_interval: 60s
timeout: 10s

connection:
  queue_manager: QM1
  channel: DEV.APP.SVRCONN
  conn_name: qm1(1414)
  user: app
  password_env: MQ_QM1_PASSWORD

metrics:
  include_queue_manager: true
  include_queues: true
  include_topics: true
  include_channels: true
  include_accounting: true
  include_statistics: true
  include_activity_trace: true
  include_system_topic_stream: true

  queue_patterns:
    - APP.*
    - SYSTEM.ADMIN.COMMAND.QUEUE
  topic_patterns:
    - SYSTEM.ADMIN.TOPIC
  channel_patterns:
    - DEV.*

  system_topic_subscription_patterns:
    - $SYS/MQ/INFO/QMGR/{qmgr}/Monitor/STATMQI/#
    - $SYS/MQ/INFO/QMGR/{qmgr}/Monitor/STATQ/#
    - $SYS/MQ/INFO/QMGR/{qmgr}/Monitor/STATAPP/#
    - $SYS/MQ/INFO/QMGR/{qmgr}/Monitor/CPU/#
    - $SYS/MQ/INFO/QMGR/{qmgr}/Monitor/DISK/#
  system_topic_max_messages_per_poll: 50000
  system_topic_diagnostics: true
  system_topic_startup_probe_window_seconds: 15
  system_topic_startup_probe_interval_seconds: 5
  amqsruac_mode: fallback
  amqsruac_fallback_interval_seconds: 300
```

Passwords may be supplied with exactly the approach appropriate to the
environment:

- `password_env`: name of an environment variable; recommended for containers
- `password_file`: path to a file containing the password
- `password`: inline value; convenient but not recommended

The Docker helper exports `MQ_QM1_PASSWORD`, defaulting to the lab password
`passw0rd`. Change all included development credentials outside an isolated lab.

### Pattern behavior

Queue, topic, and channel patterns are sent through the relevant PCF inquiries.
Broad patterns increase collection time and cardinality. A queue such as
`APP.LOCAL` is not collected unless it matches at least one configured queue
pattern.

System-topic `{qmgr}` placeholders are replaced with the configured queue
manager name. Monitoring publications are interval- and activity-driven, so
enabling a subscription does not guarantee immediate samples for every family.

`amqsruac_mode` controls the sample-client fallback:

- `fallback` (recommended): use persistent pyMQI topic subscriptions and their
  latest-value cache; invoke `amqsruac` only for classes not yet represented in
  that cache. Fallback results are cached by class and refreshed no more often
  than `amqsruac_fallback_interval_seconds` (300 seconds by default)
- `always`: run `amqsruac` every poll for validation or troubleshooting
- `disabled`: never invoke `amqsruac`

The direct subscriptions are opened once and retained with the MQ session.
Every publication is parsed once and its newest labeled values remain cached
across later polls. A broken MQ session is reconnected and its subscriptions
are recreated automatically.

### IBM MQ prerequisites

The custom image applies
[monitoring-auth.mqsc](docker_build/mq-monitoring/monitoring-auth.mqsc), which
enables the lab's accounting, statistics, monitoring, activity, and event
settings and grants its monitoring identities access to required objects.

For an independently managed queue manager, configure the corresponding MQ
attributes and authorities. At minimum, PCF collection needs access to:

- `SYSTEM.ADMIN.COMMAND.QUEUE`
- `SYSTEM.DEFAULT.MODEL.QUEUE`

Optional collectors also require their configured accounting, statistics,
activity, event, and topic objects. Missing authority normally appears as MQRC
2035; an unreachable host/port normally appears as MQRC 2538.

## HTTP endpoints

| Path | Purpose |
| --- | --- |
| `/metrics` | Cached Prometheus exposition |
| `/status` | Per-queue-manager poll state and last error |
| `/info` | Process, configuration, and runtime information |
| `/` | Endpoint index |

The Prometheus scrape interval controls how often Prometheus reads the cache.
It does not control the MQ polling interval.

## Inspect the metric surface

The repository includes a helper that prints sorted, unique metric names,
ignoring comments and labels, followed by the count:

```bash
./scripts/count_unique_metrics.sh
./scripts/count_unique_metrics.sh http://localhost:9157/metrics
```

Do not treat the count as a fixed product constant. It changes with configuration,
MQ object inventory, activity, completed statistics intervals, and collector
availability.

Useful diagnostics:

```bash
curl -fsS http://localhost:9157/status
curl -fsS http://localhost:9157/info
docker logs --tail 200 mq-pymqi-exporter
docker exec mq-pymqi-exporter sh -lc 'command -v amqsruac'
docker exec mq-pymqi-exporter sh -lc 'printf "%s\n" "$MQSERVER"'
```

## Bash helper reference

The following are the project-owned Bash helpers. Shell files shipped inside the
IBM redistributable package and generated build contexts are vendor/generated
implementation files, not operator commands.

| Script | Purpose | Default effect |
| --- | --- | --- |
| `docker_build/start_mq.sh` | Build and provision N local MQ queue managers | Recreates the stack **and deletes existing MQ data** |
| `docker_build/stop_mq.sh` | Stop the MQ Compose stack | Preserves data, image, Compose file, and network |
| `docker_build/start_pymqi_exporter.sh` | Build and run the exporter image | Replaces the named exporter container |
| `docker_build/stop_pymqi_exporter.sh` | Stop/remove exporter container | Preserves images and generated build files |
| `docker_build/start_prometheus.sh` | Generate config, build, and run Prometheus | Scrapes ports 9157–9159; UI on 9091 |
| `docker_build/stop_prometheus.sh` | Stop/remove Prometheus | Preserves image, time-series data, and generated config |
| `docker_build/start_grafana.sh` | Provision and run Grafana | UI on 3000; provisions Prometheus and dashboards |
| `docker_build/stop_grafana.sh` | Stop/remove Grafana | Preserves local data and shared network |
| `docker_build/docker_tool.sh` | Interactive Docker container utility | Read/operate on a selected container |
| `scripts/count_unique_metrics.sh` | List and count unique Prometheus names | Reads `http://localhost:9157/metrics` |

### MQ helpers

```bash
cd docker_build
./start_mq.sh <number-of-queue-managers>
./stop_mq.sh [-d] [-i] [-c] [-n] [-a]
```

`start_mq.sh` validates ports, builds `mq-local-monitoring`, removes the old
Compose stack and data, creates `data/QM*`, generates `docker-compose.yml`, and
starts the queue managers.

`stop_mq.sh` flags:

- `-d`: permanently delete MQ data
- `-i`: remove `mq-local-monitoring`
- `-c`: remove the generated Compose file
- `-n`: remove unused Compose networks
- `-a`: perform all cleanup actions

### Exporter helpers

```bash
cd docker_build
./start_pymqi_exporter.sh
./stop_pymqi_exporter.sh
```

The start helper creates a clean build context, builds pyMQI and the exporter
inside Docker with Python 3.11.9, mounts `examples` read-only, publishes port
9157, and joins `docker_build_default`.

Supported start environment overrides:

```text
BASE_IMAGE           mq-local-monitoring:latest
EXPORTER_IMAGE       mq-pymqi-exporter:latest
CONTAINER_NAME       mq-pymqi-exporter
EXPORTER_PORT        9157
PYTHON_VERSION       3.11.9
MQ_QM1_PASSWORD      passw0rd
DOCKER_NETWORK       docker_build_default
REBUILD_BASE         false
NO_CACHE             false
```

Examples:

```bash
NO_CACHE=true ./start_pymqi_exporter.sh
REBUILD_BASE=true ./start_pymqi_exporter.sh
EXPORTER_PORT=9158 CONTAINER_NAME=mq-exporter-2 ./start_pymqi_exporter.sh
```

The stop helper recognizes `CONTAINER_NAME`, `EXPORTER_IMAGE`, `BASE_IMAGE`,
`DOCKER_NETWORK`, plus these Boolean cleanup switches:

```bash
REMOVE_EXPORTER_IMAGE=true REMOVE_GENERATED_FILES=true \
  ./stop_pymqi_exporter.sh
```

`REMOVE_BASE_IMAGE=true` removes the custom MQ base image;
`REMOVE_NETWORK=true` removes the network only when possible.

### Prometheus helpers

```bash
cd docker_build
./start_prometheus.sh \
  [-h scrape-host] [-p comma-separated-ports] [-u path] \
  [-P ui-port] [-i scrape-interval] [-e evaluation-interval] \
  [-n exporter-network]

./stop_prometheus.sh [-i] [-d] [-c] [-a]
```

Start defaults are exporter container `mq-pymqi-exporter`, port `9157`, path
`/metrics`, UI port `9091`, exporter network `docker_build_default`, and
15-second scrape/evaluation intervals. Prometheus joins both its own Compose
network (for Grafana) and the exporter's network, so it scrapes
`mq-pymqi-exporter:9157` without traversing a host-published port. It generates
`prometheus/prometheus.yml`, a Dockerfile,
`docker-compose.prometheus.yml`, and persistent `prometheus-data`.

Stop flags remove the image (`-i`), time-series data (`-d`), generated files
(`-c`), or everything (`-a`). Data removal is permanent.

### Grafana helpers

```bash
cd docker_build
./start_grafana.sh \
  [-P ui-port] [-u prometheus-url] [-n network] \
  [-U admin-user] [-W admin-password]

./stop_grafana.sh [-r] [-d] [-n]
```

Start defaults are port 3000, Prometheus URL
`http://prometheus-local-monitoring:9090`, Docker network
`prometheus_local_monitoring_default`, and credentials `admin` / `admin`.
Dashboard JSON files from `dashboards` are copied and provisioned automatically.
Port `9090` is Prometheus's container port and is correct for Grafana;
`localhost:9091` is the corresponding host/browser address.

Set the Grafana password persistently in the helper's
`GRAFANA_ADMIN_PASSWORD` default, for one invocation through the environment,
or with `-W`:

```bash
GRAFANA_ADMIN_PASSWORD='choose-a-strong-password' ./start_grafana.sh
./start_grafana.sh -U admin -W 'choose-a-strong-password'
```

Stop flags remove the generated Compose file (`-r`), local Grafana data and
provisioning (`-d`), and the shared network when unused (`-n`).

### Interactive Docker utility

```bash
./docker_build/docker_tool.sh
DEFAULT_LOG_LINES=500 ./docker_build/docker_tool.sh
```

The menu can select a container, show/follow logs, open a shell, inspect stats,
processes, ports, environment and health, execute a command, copy files, restart,
stop, or remove the selected container.

## Run from source

Install into a virtual environment only after the IBM MQ client SDK is available
to the pyMQI build/runtime:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

export MQ_QM1_PASSWORD='replace-me'
python -m mq_exporter.main --config examples/exporter.yaml
```

When running on the host, change QM1's `conn_name` from `qm1(1414)` to
`localhost(1415)`.

## Request/reply diagnostic utility

`src/mq_requestreply` contains a small client that puts one message and then
drains available messages from the same queue:

```bash
python -m mq_requestreply.mq_requestreply \
  --queue-manager QM1 \
  --channel DEV.APP.SVRCONN \
  --conn-name 'localhost(1415)' \
  --user app \
  --password passw0rd \
  --queue APP.LOCAL \
  --message 'hello'
```

Most arguments also have `MQ_*` environment-variable equivalents; run with
`--help` for the complete list.

## Troubleshooting incomplete metrics

If only a handful of exporter metrics appear:

1. Read `/status` and exporter logs before relying on the raw count.
2. Confirm the exporter uses `qm1(1414)`, not `localhost(1415)`, in Docker.
3. Confirm the exporter and `qm1` are attached to `docker_build_default`.
4. Verify `amqsruac` exists in the exporter image and its client connection is
   valid.
5. Generate MQI and queue traffic, then wait for an accounting/statistics
   interval.
6. Confirm queue/channel patterns match the intended objects.
7. Check MQ authorities and whether another consumer is draining admin queues.
8. Enable `system_topic_diagnostics` and inspect startup-probe log messages.

CPU, disk, log, STATMQI, and STATAPP are not ordinary PCF object attributes.
Their absence while PCF queue metrics work usually points to the `amqsruac` or
monitoring-publication path, not basic MQ connectivity.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests cover configuration, startup/shutdown, metric storage, MQ parsing and
collection, and the request/reply utility.

## Repository layout

```text
.
├── dashboards/                 Grafana dashboards
├── docker_build/               Dockerfiles, MQSC, and stack helpers
├── examples/                   Exporter and per-QM configuration
├── scripts/                    Small user-facing utilities
├── src/mq_exporter/            Exporter implementation
├── src/mq_requestreply/        MQ request/reply diagnostic client
├── tests/                      Unit tests
├── amqsrua.py                  amqsrua-related reference/validation work
├── amqsrua_validation.md       Collector validation notes
├── pyproject.toml              Python package metadata
└── requirements.txt            Runtime dependencies
```

Generated Docker Compose files, monitoring data, build contexts, Python caches,
and local-only helpers such as `push_it.sh` are intentionally not part of the
documented source surface.

## Security and production use

The Docker stack is a development lab. It uses known passwords, publishes
unencrypted client channels, and defaults Grafana to `admin` / `admin`. Before
production use, rotate credentials, use secret files or a secret manager, enable
TLS, restrict MQ and HTTP network access, grant least privilege, pin container
image versions, and review the consequences of draining shared administration
queues.
