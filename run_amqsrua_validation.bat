@echo off
setlocal EnableExtensions

powershell -ExecutionPolicy Bypass -File "%~dp0run_amqsrua_validation.ps1" %*
exit /b %ERRORLEVEL%
