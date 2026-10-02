<#
.SYNOPSIS
  Starts the agent automatically when you sign in to Windows (current user only, no administrator rights).

.DESCRIPTION
  Uses a shortcut in your Startup folder, so it is easy to see and remove in Settings > Apps > Startup.
  Without a switch it only reports the current state.
#>
[CmdletBinding()]
param([switch]$Enable, [switch]$Disable)
. "$PSScriptRoot\_common.ps1"

$link = Join-Path ([Environment]::GetFolderPath("Startup")) "Autofill Agent.lnk"

if ($Enable -and $Disable) { throw "Choose either -Enable or -Disable." }
if ($Enable) {
    if (-not (Test-Path $script:VenvPythonW)) { throw "The agent is not installed yet. Run scripts\windows\install.ps1 first." }
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($link)
    $s.TargetPath = $script:VenvPythonW
    $s.Arguments = "-m autofill_agent"
    $s.WorkingDirectory = $script:Backend
    $s.WindowStyle = 7   # minimized; pythonw has no console anyway
    $s.Description = "Local Job Application Autofill Agent (127.0.0.1 only)"
    $s.Save()
    Write-Host "Autostart is ON. The agent will start when you sign in."
} elseif ($Disable) {
    if (Test-Path $link) { Remove-Item $link -Force }
    Write-Host "Autostart is OFF."
} else {
    Write-Host ("Autostart is " + $(if (Test-Path $link) { "ON" } else { "OFF" }) + ".")
}
