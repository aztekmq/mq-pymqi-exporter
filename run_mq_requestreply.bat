@echo off
setlocal EnableExtensions

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

set "VENV_DIR=%REPO_ROOT%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

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

echo [INFO] Installing request/reply dependencies...
"%VENV_PYTHON%" -m pip install -r "%REPO_ROOT%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    echo [ERROR] pyMQI may require IBM MQ client libraries or build prerequisites on this machine.
    exit /b 1
)

echo [INFO] Installing the project package in editable mode...
"%VENV_PYTHON%" -m pip install -e "%REPO_ROOT%"
if errorlevel 1 (
    echo [ERROR] Failed to install the project package.
    exit /b 1
)

if "%MQ_QMGR%"=="" set "MQ_QMGR=QM1"
if "%MQ_CHANNEL%"=="" set "MQ_CHANNEL=DEV.APP.SVRCONN"
if "%MQ_CONN_NAME%"=="" set "MQ_CONN_NAME=localhost(1415)"
if "%MQ_USER%"=="" set "MQ_USER=app"
if "%MQ_PASSWORD%"=="" (
    set "MQ_PASSWORD=passw0rd"
    echo [INFO] MQ_PASSWORD was not set. Defaulting to "passw0rd" for local docker_build QM1.
)
if "%MQ_REQUEST_MESSAGE%"=="" set "MQ_REQUEST_MESSAGE=ping"
if "%MQ_WAIT_TIMEOUT_MS%"=="" set "MQ_WAIT_TIMEOUT_MS=30000"
if "%MQ_QUEUE%"=="" set "MQ_QUEUE=APP.REQUEST"

if "%MQ_QUEUE%"=="" (
    echo [ERROR] MQ_QUEUE is not set.
    echo [ERROR] Example: set MQ_QUEUE=APP.REQUEST
    exit /b 1
)

echo [INFO] Starting MQ same-queue put/get utility with:
echo [INFO]   queue manager: %MQ_QMGR%
echo [INFO]   conn_name: %MQ_CONN_NAME%
echo [INFO]   channel: %MQ_CHANNEL%
echo [INFO]   user: %MQ_USER%
echo [INFO]   queue: %MQ_QUEUE%
echo [INFO]   wait timeout ms: %MQ_WAIT_TIMEOUT_MS%
echo.

"%VENV_PYTHON%" -m mq_requestreply.mq_requestreply %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] mq_requestreply exited with code %EXIT_CODE%.
)

exit /b %EXIT_CODE%
