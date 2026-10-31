# Build the desktop app (Windows)
$ErrorActionPreference = "Stop"
$py = if (Get-Command python -ErrorAction SilentlyContinue) { (Get-Command python).Source } else { "python" }
Push-Location (Resolve-Path "$PSScriptRoot\..")
& $py -m PyInstaller desktop\spotify-dashboard.spec --noconfirm
Pop-Location
Write-Host "Built: desktop\dist\reSpotIt\reSpotIt.exe"
