<#
.SYNOPSIS
  Starts the Autofill Agent on 127.0.0.1 (this computer only).

.PARAMETER Background
  Start it without a console window and return immediately.
#>
[CmdletBinding()]
param([switch]$Background)
. "$PSScriptRoot\_common.ps1"

if (-not (Test-Path $script:VenvPython)) { throw "The agent is not installed yet. Run scripts\windows\install.ps1 first." }
if (Test-AgentRunning) { Write-Host "The agent is already running on http://127.0.0.1:$($script:Port)."; return }

if ($Background) {
    Start-Process -FilePath $script:VenvPythonW -ArgumentList @("-m", "autofill_agent") -WorkingDirectory $script:Backend -WindowStyle Hidden
    for ($i = 0; $i -lt 40; $i++) {
        if (Test-AgentRunning) { Write-Host "Agent started on http://127.0.0.1:$($script:Port)."; return }
        Start-Sleep -Milliseconds 250
    }
    throw "The agent did not answer after starting. Run scripts\windows\start-agent.ps1 without -Background to see its output."
}

Write-Host "Starting the agent. Press Ctrl+C to stop it."
Set-Location $script:Backend
& $script:VenvPython -m autofill_agent
