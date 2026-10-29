# Installs everything UK TV Tool needs on Windows. Safe to run again: anything already present is skipped.
#   Python 3.12, yt-dlp, ffmpeg (winget), and get_iplayer (official GitHub release, checksum verified).
# Run from PowerShell in this folder:  powershell -ExecutionPolicy Bypass -File .\setup.ps1

$ErrorActionPreference = "Stop"
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

Step "Python 3.12"
if (Test-Path $py) {
    Write-Host "already installed"
} else {
    winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements --silent
}

Step "yt-dlp"
# -s: install into Python's own folder. A per-user (--user) copy is not seen when the app is double-clicked.
& $py -s -m pip install --upgrade --disable-pip-version-check --no-warn-script-location -r "$PSScriptRoot\requirements.txt"

Step "ffmpeg"
$ffmpeg = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($ffmpeg -or (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "already installed"
} else {
    winget install --id Gyan.FFmpeg -e --scope user --accept-package-agreements --accept-source-agreements --silent
}

Step "get_iplayer (for 1080p)"
if (Test-Path "$env:ProgramFiles\get_iplayer\get_iplayer.pl") {
    Write-Host "already installed"
} else {
    $release = Invoke-RestMethod "https://api.github.com/repos/get-iplayer/get_iplayer_win32/releases/latest"
    $asset = $release.assets | Where-Object { $_.name -like "*windows-x64-setup.exe" } | Select-Object -First 1
    $dir = Join-Path $env:TEMP "get_iplayer-setup"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $exe = Join-Path $dir $asset.name
    Write-Host "downloading $($asset.name)"
    Invoke-WebRequest $asset.browser_download_url -OutFile $exe -UseBasicParsing
    $sums = (Invoke-WebRequest "$($asset.browser_download_url).sha256" -UseBasicParsing).Content
    if ($sums -is [byte[]]) { $sums = [Text.Encoding]::ASCII.GetString($sums) }
    $expected = ($sums.Trim() -split '\s+')[0]
    if ((Get-FileHash $exe -Algorithm SHA256).Hash -ne $expected) { throw "get_iplayer download failed its checksum" }
    Write-Host "installing (Windows may ask for permission)"
    Start-Process $exe -ArgumentList "/S" -Wait
    Remove-Item -Recurse -Force $dir
}

Step "Done"
Write-Host "Start the app with 'UK TV Tool.bat'."
