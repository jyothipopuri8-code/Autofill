# Shared helpers for the Windows scripts. Dot-source it: . "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Stop"

$script:Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script:Venv = Join-Path $script:Root ".venv"
$script:VenvPython = Join-Path $script:Venv "Scripts\python.exe"
$script:VenvPythonW = Join-Path $script:Venv "Scripts\pythonw.exe"
$script:Backend = Join-Path $script:Root "backend"
$script:Extension = Join-Path $script:Root "extension"
$script:Port = if ($env:AUTOFILL_PORT) { [int]$env:AUTOFILL_PORT } else { 8765 }
$script:DataDir = if ($env:AUTOFILL_DATA_DIR) { $env:AUTOFILL_DATA_DIR } else { Join-Path $env:LOCALAPPDATA "AutofillAgent" }

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Warn([string]$Text) { Write-Host "WARNING: $Text" -ForegroundColor Yellow }

# Returns @(exe, extra-args...) for the first Python >= 3.11 found, or $null.
function Find-Python {
    $candidates = @(
        @("py", "-3.12"), @("py", "-3.11"), @("py", "-3"), @("python3"), @("python")
    )
    foreach ($c in $candidates) {
        $exe = $c[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $extra = @($c | Select-Object -Skip 1)
        try {
            $ok = & $exe @extra -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null
            if ($ok -eq "1") { return $c }
        } catch { }
    }
    return $null
}

# True when an agent already answers on the loopback port.
function Test-AgentRunning {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$($script:Port)/api/v1/health" -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}
