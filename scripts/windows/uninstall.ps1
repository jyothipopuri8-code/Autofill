<#
.SYNOPSIS
  Removes autostart and (optionally) your stored data. Your data is kept unless you ask for it to be deleted.

.PARAMETER DeleteData
  Also delete the agent's data folder: profile, resumes, answers, application history, logs and the install token.
  This cannot be undone, so you are asked to type DELETE to confirm.
#>
[CmdletBinding()]
param([switch]$DeleteData)
. "$PSScriptRoot\_common.ps1"

& "$PSScriptRoot\autostart.ps1" -Disable

if ($DeleteData -and (Test-AgentRunning)) { throw "The agent is still running. Close its window (or sign out), then run this again." }

if ($DeleteData) {
    Write-Host "This will permanently delete: $($script:DataDir)"
    $answer = Read-Host "Type DELETE to confirm"
    if ($answer -ceq "DELETE") {
        if (Test-Path $script:DataDir) { Remove-Item $script:DataDir -Recurse -Force }
        Write-Host "Deleted."
    } else { Write-Host "Cancelled. Nothing was deleted." }
} else {
    Write-Host "Your data in $($script:DataDir) was left in place. Use -DeleteData to remove it."
}
Write-Host "To remove the program itself, delete this folder and the extension in chrome://extensions."
