#!/usr/bin/env pwsh
<#
.SYNOPSIS
Build and start a local Prometheus container that scrapes the exporter on the host.

.DESCRIPTION
Generates a dedicated Prometheus configuration and compose file under docker_build,
builds a local image based on prom/prometheus, and starts Prometheus bound to the
local workstation. The scrape target defaults to host.docker.internal:9157 so the
container can reach the exporter running natively on the host.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$ScrapeHost = "host.docker.internal",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$ScrapePort = 9157,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$ScrapePath = "/metrics",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$PrometheusPort = 9090,

    [Parameter(Mandatory = $false)]
    [ValidatePattern("^[0-9]+(ms|s|m|h)$")]
    [string]$ScrapeInterval = "15s",

    [Parameter(Mandatory = $false)]
    [ValidatePattern("^[0-9]+(ms|s|m|h)$")]
    [string]$EvaluationInterval = "15s"
)

$ErrorActionPreference = "Stop"

$ImageName = "prometheus-local-monitoring"
$ContainerName = "prometheus-local-monitoring"
$PrometheusDir = Join-Path -Path $PSScriptRoot -ChildPath "prometheus"
$DataDir = Join-Path -Path $PSScriptRoot -ChildPath "prometheus-data"
$ConfigFile = Join-Path -Path $PrometheusDir -ChildPath "prometheus.yml"
$Dockerfile = Join-Path -Path $PrometheusDir -ChildPath "Dockerfile"
$ComposeFile = Join-Path -Path $PSScriptRoot -ChildPath "docker-compose.prometheus.yml"

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

Write-Step "Checking for Prometheus UI port conflicts..."
if (-not (Test-PortAvailable -Port $PrometheusPort)) {
    Write-Failure "Port $PrometheusPort is already in use. Cannot continue."
    exit 1
}
Write-Success "Prometheus UI port $PrometheusPort is available."

Write-Step "Checking Docker availability..."
$null = docker version
$null = docker compose version

Write-Step "Preparing Prometheus build context..."
New-Item -ItemType Directory -Path $PrometheusDir -Force | Out-Null
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null

$scrapeTarget = "{0}:{1}" -f $ScrapeHost, $ScrapePort
$configLines = @(
    "global:"
    "  scrape_interval: $ScrapeInterval"
    "  evaluation_interval: $EvaluationInterval"
    ""
    "scrape_configs:"
    "  - job_name: 'mq_pymqi_exporter'"
    "    metrics_path: '$ScrapePath'"
    "    static_configs:"
    "      - targets: ['${scrapeTarget}']"
)
[System.IO.File]::WriteAllLines($ConfigFile, $configLines)

$dockerfileLines = @(
    "FROM prom/prometheus:latest"
    "COPY prometheus.yml /etc/prometheus/prometheus.yml"
)
[System.IO.File]::WriteAllLines($Dockerfile, $dockerfileLines)

$composeLines = @(
    "services:"
    "  prometheus:"
    "    build:"
    "      context: ./prometheus"
    "    image: $ImageName"
    "    container_name: $ContainerName"
    "    ports:"
    "      - `"127.0.0.1:$($PrometheusPort):9090`""
    "    extra_hosts:"
    "      - `"host.docker.internal:host-gateway`""
    "    volumes:"
    "      - ./prometheus-data:/prometheus"
    "    restart: unless-stopped"
)
[System.IO.File]::WriteAllLines($ComposeFile, $composeLines)

Write-Step "Building local Prometheus image..."
docker build -t $ImageName $PrometheusDir

Write-Step "Starting Prometheus container..."
docker compose -f $ComposeFile up -d

Write-Success "Prometheus is ready."
Write-Host ""
Write-Host "Deployment Summary:" -ForegroundColor Yellow
Write-Host "Prometheus UI  : http://localhost:$PrometheusPort/" -ForegroundColor White
Write-Host "Scrape target  : http://$ScrapeHost`:$ScrapePort$ScrapePath" -ForegroundColor White
Write-Host "Image name     : $ImageName" -ForegroundColor White
Write-Host "Container name : $ContainerName" -ForegroundColor White
