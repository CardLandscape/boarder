param(
    [string]$Distro = "Debian",
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$projectRootPosix = "/mnt/" + $projectRoot.Substring(0,1).ToLower() + $projectRoot.Substring(2).Replace("\\","/")
$liveBuildRoot = "$projectRootPosix/iso/live-build"

Write-Host "[1/5] Checking WSL distro..."
$distros = (wsl --list --quiet) -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
if (-not ($distros -contains $Distro)) {
    throw "WSL distro '$Distro' not found. Install it first: wsl --install -d $Distro"
}

Write-Host "[2/5] Installing live-build dependencies in WSL..."
wsl -d $Distro -- bash -lc "sudo apt-get update && sudo apt-get install -y live-build rsync xorriso"

Write-Host "[3/5] Syncing application files into live-build includes..."
$includeRoot = Join-Path $projectRoot "iso\live-build\config\includes.chroot\opt\border-control"
if (Test-Path $includeRoot) {
    Get-ChildItem -Force $includeRoot | Remove-Item -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $includeRoot | Out-Null

$copyItems = @(
    "main.py",
    "requirements.txt",
    "README.md",
    "passenger_data.json",
    "data",
    "scripts"
)
foreach ($item in $copyItems) {
    $src = Join-Path $projectRoot $item
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $includeRoot -Recurse -Force
    }
}

Write-Host "[4/5] Building bootable ISO with live-build..."
wsl -d $Distro -- bash -lc "chmod +x '$projectRootPosix/scripts/build_iso_linux.sh' && '$projectRootPosix/scripts/build_iso_linux.sh'"

Write-Host "[5/5] Collecting artifact..."
$outputPath = Join-Path $projectRoot $OutputDir
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$isoSource = Get-ChildItem -Path (Join-Path $projectRoot "dist") -Filter "*.iso" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $isoSource) {
    throw "ISO artifact not found in dist directory."
}
$isoTarget = Join-Path $outputPath $isoSource.Name
Copy-Item -Path $isoSource.FullName -Destination $isoTarget -Force

Write-Host "ISO ready: $isoTarget"
