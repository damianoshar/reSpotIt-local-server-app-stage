# Build the desktop app (Windows)
$ErrorActionPreference = "Stop"
$py = "C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe"
Push-Location (Resolve-Path "$PSScriptRoot\..")
& $py -m PyInstaller desktop\spotify-dashboard.spec --noconfirm
Pop-Location
Write-Host "Built: desktop\dist\reSpotIt\reSpotIt.exe"
