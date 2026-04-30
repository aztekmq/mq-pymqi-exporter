<#
.SYNOPSIS
Builds an IBM MQ container image on Windows with verbose diagnostics.

.DESCRIPTION
This script provides a Windows-native build workflow that mirrors common
`build_mq.sh` behavior while adding structured logging and validation.

The script:
1. Validates required tooling.
2. Emits timestamped, verbose log records for every action.
3. Runs `docker build` with configurable parameters.
4. Returns a non-zero exit code when failures occur.

.NOTES
Author: Codex Assistant
Standards:
- ISO/IEC/IEEE 12207-aligned operational scripting conventions.
- Comment-based PowerShell help for maintainability.
- Explicit input validation and deterministic exit signaling.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$ImageName = 'mq-custom:latest',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$Dockerfile = 'Dockerfile',

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$Context = '.',

    [Parameter(Mandatory = $false)]
    [switch]$NoCache,

    [Parameter(Mandatory = $false)]
    [switch]$Pull,

    [Parameter(Mandatory = $false)]
    [string]$LogDirectory = '.\\logs'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Log {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('INFO', 'WARN', 'ERROR', 'DEBUG')]
        [string]$Level,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $timestamp = Get-Date -Format 'yyyy-MM-ddTHH:mm:ss.fffK'
    $line = "[$timestamp] [$Level] $Message"
    switch ($Level) {
        'ERROR' { Write-Error $line }
        'WARN'  { Write-Warning $line }
        'DEBUG' { Write-Verbose $line }
        default { Write-Host $line }
    }
}

function Assert-CommandAvailable {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$CommandName
    )

    if (-not (Get-Command -Name $CommandName -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $CommandName"
    }
}

try {
    New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
    $logFile = Join-Path -Path $LogDirectory -ChildPath ("build_mq_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
    Start-Transcript -Path $logFile -Force | Out-Null

    Write-Log -Level INFO -Message 'Starting MQ image build script.'
    Write-Log -Level INFO -Message "ImageName=$ImageName; Dockerfile=$Dockerfile; Context=$Context; NoCache=$NoCache; Pull=$Pull"

    Assert-CommandAvailable -CommandName 'docker'

    if (-not (Test-Path -Path $Dockerfile -PathType Leaf)) {
        throw "Dockerfile path does not exist: $Dockerfile"
    }

    if (-not (Test-Path -Path $Context -PathType Container)) {
        throw "Build context path does not exist: $Context"
    }

    $dockerArgs = @('build', '--progress=plain', '-f', $Dockerfile, '-t', $ImageName)
    if ($NoCache.IsPresent) { $dockerArgs += '--no-cache' }
    if ($Pull.IsPresent) { $dockerArgs += '--pull' }
    $dockerArgs += $Context

    Write-Log -Level DEBUG -Message ("Executing command: docker {0}" -f ($dockerArgs -join ' '))
    & docker @dockerArgs
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        throw "docker build failed with exit code $exitCode"
    }

    Write-Log -Level INFO -Message 'MQ image build completed successfully.'
    exit 0
}
catch {
    Write-Log -Level ERROR -Message $_.Exception.Message
    exit 1
}
finally {
    try {
        Stop-Transcript | Out-Null
    }
    catch {
        # No-op: transcript may not have started.
    }
}
