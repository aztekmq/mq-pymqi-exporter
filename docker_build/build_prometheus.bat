@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0build_prometheus.ps1" %*
exit /b %errorlevel%
