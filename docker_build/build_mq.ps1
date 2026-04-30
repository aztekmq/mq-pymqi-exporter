#!/usr/bin/env pwsh
<#
.SYNOPSIS
Provision N IBM MQ queue managers as Docker containers on Windows.

.DESCRIPTION
Generates docker-compose.yml, recreates the local data directory, starts the
containers, and prints a summary of the assigned host ports.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateRange(1, 1000)]
    [int]$NumberOfQmgrs
)

$ErrorActionPreference = "Stop"

$BaseListenerPort = 1414
$BaseWebPort = 9443
$BaseRestPort = 9449
$DataDir = Join-Path -Path $PSScriptRoot -ChildPath "data"
$ComposeFile = Join-Path -Path $PSScriptRoot -ChildPath "docker-compose.yml"
$ImageName = "ibmcom/mq"

function Write-Step {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Green
}

function Write-Failure {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Test-PortAvailable {
    param([int]$Port)

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -eq $listener
}

Write-Step "Checking for port conflicts..."

for ($i = 1; $i -le $NumberOfQmgrs; $i++) {
    $ports = @(
        $BaseListenerPort + $i
        $BaseWebPort + $i
        $BaseRestPort + $i
    )

    foreach ($port in $ports) {
        if (-not (Test-PortAvailable -Port $port)) {
            Write-Failure "Port $port is already in use. Cannot continue."
            exit 1
        }
    }
}

Write-Success "No port conflicts detected."

Write-Step "Checking Docker availability..."
$null = docker version
$null = docker compose version

Write-Step "Cleaning up old containers and volumes..."
docker compose down --remove-orphans | Out-Null

if (Test-Path -LiteralPath $ComposeFile) {
    Remove-Item -LiteralPath $ComposeFile -Force
}

if (Test-Path -LiteralPath $DataDir) {
    Remove-Item -LiteralPath $DataDir -Recurse -Force
}

Write-Step "Creating data directories..."
for ($i = 1; $i -le $NumberOfQmgrs; $i++) {
    $qmgrName = "QM$i"
    $qmgrPath = Join-Path -Path $DataDir -ChildPath $qmgrName
    New-Item -ItemType Directory -Path $qmgrPath -Force | Out-Null
}

Write-Step "Generating docker-compose.yml..."
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("version: '3.8'")
$lines.Add("services:")

for ($i = 1; $i -le $NumberOfQmgrs; $i++) {
    $qmgrName = "QM$i"
    $containerName = $qmgrName.ToLowerInvariant()
    $listenerPort = $BaseListenerPort + $i
    $webPort = $BaseWebPort + $i
    $restPort = $BaseRestPort + $i

    $lines.Add("  ${containerName}:")
    $lines.Add("    image: $ImageName")
    $lines.Add("    container_name: $containerName")
    $lines.Add("    environment:")
    $lines.Add("      - LICENSE=accept")
    $lines.Add("      - MQ_QMGR_NAME=$qmgrName")
    $lines.Add("      - MQ_APP_PASSWORD=passw0rd")
    $lines.Add("      - MQ_ENABLE_METRICS=true")
    $lines.Add("      - MQ_ENABLE_ADMIN_WEB=true")
    $lines.Add("    ports:")
    $lines.Add("      - `"$($listenerPort):1414`"")
    $lines.Add("      - `"$($webPort):9443`"")
    $lines.Add("      - `"$($restPort):9449`"")
    $lines.Add("    volumes:")
    $lines.Add("      - ./data/${qmgrName}:/mnt/mqm")
    $lines.Add("    healthcheck:")
    $lines.Add("      test: [`"CMD`", `"mqcli`", `"status`"]")
    $lines.Add("      interval: 30s")
    $lines.Add("      timeout: 10s")
    $lines.Add("      retries: 5")
    $lines.Add("    restart: unless-stopped")
    $lines.Add("")
}

[System.IO.File]::WriteAllLines($ComposeFile, $lines)

Write-Step "Starting up $NumberOfQmgrs IBM MQ containers..."
docker compose up -d

Write-Success "All containers started successfully."
Write-Host ""
Write-Host "Deployment Summary:" -ForegroundColor Yellow

$summary = for ($i = 1; $i -le $NumberOfQmgrs; $i++) {
    [pscustomobject]@{
        QMGR          = "QM$i"
        ContainerName = "qm$i"
        ListenerPort  = $BaseListenerPort + $i
        WebPort       = $BaseWebPort + $i
        RestPort      = $BaseRestPort + $i
    }
}

$summary | Format-Table -AutoSize

Write-Host ""
Write-Host "To connect to a container:" -ForegroundColor Cyan
Write-Host "docker exec -it <container_name> bash" -ForegroundColor Cyan
