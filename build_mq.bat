@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0build_mq.ps1" %*
exit /b %errorlevel%
