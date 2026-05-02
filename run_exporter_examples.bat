@echo off
setlocal EnableExtensions

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

set "VENV_DIR=%REPO_ROOT%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "EXPORTER_CONFIG=%REPO_ROOT%\examples\exporter.yaml"

if not exist "%EXPORTER_CONFIG%" (
    echo [ERROR] Exporter config not found: "%EXPORTER_CONFIG%"
    exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python Launcher ^("py"^) was not found on PATH.
    echo Install Python 3 for Windows and ensure the launcher is available.
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo [INFO] Creating virtual environment in "%VENV_DIR%"...
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
)

echo [INFO] Upgrading pip, setuptools, and wheel...
"%VENV_PYTHON%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [ERROR] Failed to upgrade packaging tools.
    exit /b 1
)

echo [INFO] Installing exporter dependencies...
"%VENV_PYTHON%" -m pip install -r "%REPO_ROOT%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    echo [ERROR] pyMQI may require IBM MQ client libraries or build prerequisites on this machine.
    exit /b 1
)

echo [INFO] Installing the exporter package in editable mode...
"%VENV_PYTHON%" -m pip install -e "%REPO_ROOT%"
if errorlevel 1 (
    echo [ERROR] Failed to install the exporter package.
    exit /b 1
)

if "%MQ_QM1_PASSWORD%"=="" (
    set "MQ_QM1_PASSWORD=passw0rd"
    echo [INFO] MQ_QM1_PASSWORD was not set. Defaulting to "passw0rd" for local docker_build QM1.
) else (
    echo [INFO] Using existing MQ_QM1_PASSWORD environment variable.
)

echo [INFO] Starting exporter with config "%EXPORTER_CONFIG%"...
echo [INFO] Endpoints:
echo [INFO]   http://localhost:9157/
echo [INFO]   http://localhost:9157/info
echo [INFO]   http://localhost:9157/status
echo [INFO]   http://localhost:9157/metrics
echo [INFO] Local docker_build QM1 defaults:
echo [INFO]   queue manager: QM1
echo [INFO]   conn_name: localhost^(1415^)
echo [INFO]   channel: DEV.APP.SVRCONN
echo.

"%VENV_PYTHON%" -m mq_exporter.main --config "%EXPORTER_CONFIG%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Exporter exited with code %EXIT_CODE%.
)

exit /b %EXIT_CODE%
