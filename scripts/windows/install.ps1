<#
.SYNOPSIS
  Sets up the Autofill Agent for the current Windows user. No administrator rights are needed.

.DESCRIPTION
  Creates a Python virtual environment in .venv, installs the agent into it and (when Node.js is present)
  builds the browser extension into extension\dist. It never starts anything and never opens a network port.
  Re-running it is safe: it repairs or updates the same environment.

  NOTE: written for Windows 10/11 but only exercised on Linux so far. See docs/WINDOWS.md.
#>
[CmdletBinding()]
param(
    [switch]$SkipExtension   # do not build the extension (use a prebuilt extension zip instead)
)
. "$PSScriptRoot\_common.ps1"

Write-Step "Looking for Python 3.11 or newer"
$py = Find-Python
if (-not $py) {
    throw "Python 3.11+ was not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this script again."
}
$pyExe = $py[0]; $pyArgs = @($py | Select-Object -Skip 1)
Write-Host ("Using: " + (& $pyExe @pyArgs --version))

Write-Step "Creating the virtual environment (.venv)"
if (-not (Test-Path $script:VenvPython)) { & $pyExe @pyArgs -m venv $script:Venv; if ($LASTEXITCODE) { throw "Could not create the virtual environment." } }

Write-Step "Installing the agent"
& $script:VenvPython -m pip install --upgrade pip | Out-Null
& $script:VenvPython -m pip install -e $script:Backend
if ($LASTEXITCODE) { throw "pip could not install the agent." }

if (-not $SkipExtension) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Step "Building the browser extension"
        Push-Location $script:Extension
        try {
            npm ci; if ($LASTEXITCODE) { throw "npm ci failed." }
            npm run build; if ($LASTEXITCODE) { throw "The extension build failed." }
        } finally { Pop-Location }
    } else {
        Write-Warn "Node.js was not found, so the extension was not built. Install Node 20+ from https://nodejs.org and run this script again, or use a prebuilt extension zip."
    }
}

Write-Step "Done"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Start the agent:     scripts\windows\start-agent.bat   (or: scripts\windows\start-agent.ps1)"
Write-Host "  2. Load the extension:  chrome://extensions (or edge://extensions) -> Developer mode -> Load unpacked -> $($script:Extension)\dist"
Write-Host "  3. Pair it:             run  .venv\Scripts\python.exe -m autofill_agent token  and paste the result into the extension popup"
Write-Host "  4. Review page:         http://127.0.0.1:$($script:Port)/ui/"
Write-Host "  5. Optional:            scripts\windows\autostart.ps1 -Enable   (start the agent when you sign in)"
