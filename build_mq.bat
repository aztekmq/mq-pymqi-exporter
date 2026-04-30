@echo off
setlocal

REM ============================================================================
REM Script Name : build_mq.bat
REM Purpose     : Windows entrypoint for MQ image build automation.
REM Standard    : Delegates to documented PowerShell implementation.
REM ============================================================================

set SCRIPT_DIR=%~dp0
set PS_SCRIPT=%SCRIPT_DIR%build_mq.ps1

if not exist "%PS_SCRIPT%" (
  echo [ERROR] PowerShell script not found: "%PS_SCRIPT%"
  exit /b 1
)

echo [INFO] Launching PowerShell build script with verbose logging...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -Verbose %*
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo [ERROR] MQ build failed with exit code %EXIT_CODE%.
  exit /b %EXIT_CODE%
)

echo [INFO] MQ build completed successfully.
exit /b 0
