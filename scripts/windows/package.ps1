<#
.SYNOPSIS
  Builds files you can hand to another person: the extension zip and, optionally, a standalone agent folder.

.PARAMETER Exe
  Also build a standalone agent (autofill-agent.exe) with PyInstaller, so Python need not be installed.

  Output goes to .\release. Nothing is uploaded anywhere.
  NOTE: only exercised on Linux so far; see docs/WINDOWS.md for what still needs testing on Windows.
#>
[CmdletBinding()]
param([switch]$Exe)
. "$PSScriptRoot\_common.ps1"

if (-not (Test-Path $script:VenvPython)) { throw "Run scripts\windows\install.ps1 first." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js 20+ is required to build the extension." }
$release = Join-Path $script:Root "release"
New-Item -ItemType Directory -Force -Path $release | Out-Null

Write-Step "Building the extension"
Push-Location $script:Extension
try {
    npm ci; if ($LASTEXITCODE) { throw "npm ci failed." }
    npm test; if ($LASTEXITCODE) { throw "The extension tests failed." }
    npm run build; if ($LASTEXITCODE) { throw "The extension build failed." }
} finally { Pop-Location }
$extZip = Join-Path $release "autofill-extension.zip"
if (Test-Path $extZip) { Remove-Item $extZip -Force }
Compress-Archive -Path (Join-Path $script:Extension "dist\*") -DestinationPath $extZip
Write-Host "Wrote $extZip"

if ($Exe) {
    Write-Step "Building the standalone agent (PyInstaller)"
    & $script:VenvPython -m pip install pyinstaller
    if ($LASTEXITCODE) { throw "Could not install PyInstaller." }
    & $script:VenvPython -m PyInstaller (Join-Path $script:Root "packaging\autofill-agent.spec") --noconfirm `
        --distpath (Join-Path $release "dist") --workpath (Join-Path $script:Root "build\pyinstaller")
    if ($LASTEXITCODE) { throw "PyInstaller failed." }
    $agentZip = Join-Path $release "autofill-agent-windows.zip"
    if (Test-Path $agentZip) { Remove-Item $agentZip -Force }
    Compress-Archive -Path (Join-Path $release "dist\autofill-agent") -DestinationPath $agentZip
    Write-Host "Wrote $agentZip"
}

Write-Step "Checksums"
$sums = Get-ChildItem $release -Filter *.zip | ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name }
$sums | Set-Content -Path (Join-Path $release "SHA256SUMS.txt") -Encoding ascii
$sums | ForEach-Object { Write-Host $_ }
