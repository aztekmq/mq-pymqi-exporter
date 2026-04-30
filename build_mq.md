# IBM MQ Multi-Queue Manager Builder (Docker)

**Scripts:** `build_mq.sh`, `build_mq.ps1`, `build_mq.bat`  
**Purpose:** Provision **N** IBM MQ queue managers as Docker containers with the **Admin Web Console** and **REST Admin** endpoints exposed.  
**Author:** Aztekmq, LLC  
**Initial Release:** 2025-04-14 (ISO 8601)

---

## 1. Scope and Audience
This document describes how to use, operate, and maintain the MQ builder utilities on Linux, macOS, and Windows.

---

## 2. Overview
The scripts generate a `docker-compose.yml` and launch **N** IBM MQ containers. For each container:
- A unique listener port is mapped to container port `1414`.
- A unique Admin Web port is mapped to container port `9443`.
- A unique Admin REST port is mapped to container port `9449`.
- A persistent data directory is created under `./data/QM<i>`.

The scripts also perform:
- Port conflict detection before startup.
- Cleanup of an old Compose stack and generated data.
- Healthchecks using `mqcli status`.

---

## 3. Requirements
- Docker Desktop or Docker Engine with Compose v2.
- Linux or macOS: Bash for `build_mq.sh`.
- Windows: PowerShell 5.1+ for `build_mq.ps1` or `build_mq.bat`.

---

## 4. Usage

### Windows
```powershell
.\build_mq.ps1 3
```

or

```bat
build_mq.bat 3
```

### Linux or macOS
```bash
chmod +x build_mq.sh
./build_mq.sh 3
```

---

## 5. What Happens
1. Validates that the queue manager count is a positive integer.
2. Checks whether the computed host ports are already in use.
3. Runs `docker compose down --remove-orphans`.
4. Recreates `./data/QM<i>` directories.
5. Generates `docker-compose.yml`.
6. Runs `docker compose up -d`.
7. Prints a deployment summary.

---

## 6. Port Mapping
For queue manager `i` in `1..N`:

| Item | Host Port | Container Port |
|---|---:|---:|
| Listener | `1414 + i` | `1414` |
| Admin Web | `9443 + i` | `9443` |
| Admin REST | `9449 + i` | `9449` |

Example for `N=2`:
- `QM1` -> listener `1415`, web `9444`, REST `9450`
- `QM2` -> listener `1416`, web `9445`, REST `9451`

---

## 7. Notes for Windows
- The PowerShell script uses `Get-NetTCPConnection` for port checks.
- It removes and recreates the local `data` directory using normal Windows filesystem commands.
- It assumes Docker Desktop is installed and `docker` is available on `PATH`.

---

## 8. Security
- `MQ_APP_PASSWORD=passw0rd` is a development placeholder and should be changed for any non-lab use.
- Set `MQ_ADMIN_PASSWORD` before exposing administrative endpoints outside your laptop.
- Restrict access to ports `9443` and `9449` when not needed.

---

## 9. Change History
| Date (YYYY-MM-DD) | Version | Author | Change |
|---|---:|---|---|
| 2025-04-14 | 1.0.0 | Aztekmq, LLC | Initial release |
| 2026-04-30 | 1.0.2 | OpenAI Codex | Added Windows PowerShell and batch launch support |
