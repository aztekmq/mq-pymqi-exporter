param(
    [string]$QueueManager = "QM1",
    [string]$ExporterBaseUrl = "http://localhost:9157",
    [string]$AmqsruaPath = "",
    [int]$PublicationCount = 1
)

$ErrorActionPreference = "Stop"

function Resolve-AmqsruaPath {
    param([string]$RequestedPath)

    if ($RequestedPath -and (Test-Path -LiteralPath $RequestedPath)) {
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    $command = Get-Command amqsrua.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    if ($env:MQ_INSTALLATION_PATH) {
        $candidate = Join-Path $env:MQ_INSTALLATION_PATH "tools\c\Samples\Bin64\amqsrua.exe"
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return ""
}

function Show-Checklist {
    param([string]$ResolvedAmqsruaPath)

    Write-Host ""
    Write-Host "[CHECKLIST] Exporter"
    Write-Host "  1. GET $ExporterBaseUrl/status"
    Write-Host "  2. GET $ExporterBaseUrl/metrics"
    Write-Host "  3. Confirm ibmmq_exporter_target_up{qmgr=""$QueueManager""} is 1"
    Write-Host "  4. Confirm ibmmq_system_topic_messages_consumed is non-zero only if metadata discovery succeeds"

    Write-Host ""
    Write-Host "[CHECKLIST] IBM sample amqsrua"
    if ($ResolvedAmqsruaPath) {
        Write-Host "  Binary: $ResolvedAmqsruaPath"
    } else {
        Write-Host "  Binary not found. Install IBM MQ samples or set -AmqsruaPath."
    }
    Write-Host "  Suggested commands:"
    Write-Host "    amqsrua -m $QueueManager -c CPU -t QMgrSummary -n $PublicationCount"
    Write-Host "    amqsrua -m $QueueManager -c DISK -t Log -n $PublicationCount"
    Write-Host "    amqsrua -m $QueueManager -c STATMQI -t PUT -n $PublicationCount"
    Write-Host ""
}

function Invoke-AmqsruaCommand {
    param(
        [string]$BinaryPath,
        [string[]]$Arguments
    )

    Write-Host ""
    Write-Host "[RUN] $BinaryPath $($Arguments -join ' ')"
    & $BinaryPath @Arguments
}

$resolvedAmqsruaPath = Resolve-AmqsruaPath -RequestedPath $AmqsruaPath

Write-Host "[INFO] Exporter base URL: $ExporterBaseUrl"
Write-Host "[INFO] Queue manager: $QueueManager"
if ($resolvedAmqsruaPath) {
    Write-Host "[INFO] amqsrua path: $resolvedAmqsruaPath"
} else {
    Write-Host "[WARN] amqsrua.exe was not found."
}

Write-Host ""
Write-Host "[STEP] Exporter status"
try {
    $status = Invoke-RestMethod -Uri "$ExporterBaseUrl/status" -Method Get
    $status | ConvertTo-Json -Depth 8
} catch {
    Write-Host "[WARN] Failed to query $ExporterBaseUrl/status"
    Write-Host $_
}

Write-Host ""
Write-Host "[STEP] Exporter metric summary"
try {
    $metrics = (Invoke-WebRequest -Uri "$ExporterBaseUrl/metrics" -Method Get).Content
    $interesting = $metrics -split "`n" | Where-Object {
        $_ -match "^ibmmq_exporter_target_up" -or
        $_ -match "^ibmmq_system_topic_messages_consumed" -or
        $_ -match "^ibmmq_statistics_messages_consumed" -or
        $_ -match "^ibmmq_accounting_messages_consumed"
    }
    if ($interesting) {
        $interesting | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "[WARN] No interesting summary metrics matched."
    }
} catch {
    Write-Host "[WARN] Failed to query $ExporterBaseUrl/metrics"
    Write-Host $_
}

if (-not $resolvedAmqsruaPath) {
    Show-Checklist -ResolvedAmqsruaPath $resolvedAmqsruaPath
    exit 0
}

Invoke-AmqsruaCommand -BinaryPath $resolvedAmqsruaPath -Arguments @("-m", $QueueManager, "-c", "CPU", "-t", "QMgrSummary", "-n", "$PublicationCount")
Invoke-AmqsruaCommand -BinaryPath $resolvedAmqsruaPath -Arguments @("-m", $QueueManager, "-c", "DISK", "-t", "Log", "-n", "$PublicationCount")
Invoke-AmqsruaCommand -BinaryPath $resolvedAmqsruaPath -Arguments @("-m", $QueueManager, "-c", "STATMQI", "-t", "PUT", "-n", "$PublicationCount")

Show-Checklist -ResolvedAmqsruaPath $resolvedAmqsruaPath
