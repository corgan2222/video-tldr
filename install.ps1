# Installs the video-tldr service from a GitHub release.
#
#   irm https://raw.githubusercontent.com/corgan2222/video-tldr/main/install.ps1 | iex
#
# The extension is a separate download: the .zip attached to the same
# release, loaded through about:debugging or chrome://extensions.
#
# What this does: pick the extra that fits the machine, stop a running
# service so Windows frees its script, install the wheel with uv, and put
# the shim on the PATH. It registers no autostart and no service; the
# extension starts the service when it needs one.

[CmdletBinding()]
param(
    # A release tag such as v0.1.57. Default: the newest release.
    [string]$Version,

    # "gpu" brings the CUDA libraries (about 2 GB of wheels), "cpu" the
    # ONNX runtime alone (about 250 MB). Default: gpu when nvidia-smi
    # answers, cpu otherwise.
    [ValidateSet('gpu', 'cpu', 'auto')]
    [string]$Extra = 'auto',

    # Put the program, its environment and its data under one directory,
    # in bin\, tools\ and data\. Without this each goes to its own
    # standard place: ~\.local\bin, uv's tool directory, ~\.video-tldr.
    [string]$Root,

    # Where config.json, serve.log and the speech models live. Overrides
    # the data directory -Root would choose.
    [string]$DataDir,

    [string]$Repo = 'corgan2222/video-tldr'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$PackageName = 'video-tldr-service'

function Write-Step($message) { Write-Host "==> $message" }

# uv carries the Python, resolves the dependencies and writes the shim.
# Installing it means running someone else's script, so this asks instead
# of doing it: the caller decides whether to run that code.
function Get-Uv {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) { return $uv.Source }
    throw @"
uv is not installed, and this script will not fetch and run a remote
installer for you. Install it first, then run this again:

    irm https://astral.sh/uv/install.ps1 | iex

or with winget:

    winget install --id=astral-sh.uv -e
"@
}

function Get-Release {
    $url = if ($Version) {
        "https://api.github.com/repos/$Repo/releases/tags/$Version"
    }
    else {
        "https://api.github.com/repos/$Repo/releases/latest"
    }
    try {
        return Invoke-RestMethod -Uri $url -Headers @{ 'User-Agent' = 'video-tldr-install' }
    }
    catch {
        throw "no release found at $url : $($_.Exception.Message)"
    }
}

function Save-Asset($release, $pattern, $directory) {
    $asset = $release.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
    if (-not $asset) {
        throw "release $($release.tag_name) has no asset matching $pattern"
    }
    $target = Join-Path $directory $asset.name
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $target
    return $target
}

# A CUDA machine wants the gpu extra; everything else would download two
# gigabytes of libraries it cannot use.
function Resolve-Extra {
    if ($Extra -ne 'auto') { return $Extra }
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        & nvidia-smi | Out-Null
        if ($LASTEXITCODE -eq 0) { return 'gpu' }
    }
    return 'cpu'
}

# Windows keeps an installed console script open while the process behind
# it runs, and uv cannot replace it then. The service answers `stop`.
function Stop-RunningService($binDirectory) {
    $exe = Join-Path $binDirectory 'video-tldr.exe'
    if (-not (Test-Path $exe)) { return }
    Write-Step 'Stopping a running service'
    & $exe stop 2>&1 | Write-Host
}

function Add-ToUserPath($directory) {
    $current = [Environment]::GetEnvironmentVariable('PATH', 'User')
    $entries = @()
    if ($current) { $entries = $current -split ';' | Where-Object { $_ } }
    if ($entries -contains $directory) { return }
    $updated = (@($directory) + $entries) -join ';'
    [Environment]::SetEnvironmentVariable('PATH', $updated, 'User')
    $env:PATH = "$directory;$env:PATH"
    Write-Step "Added $directory to your PATH; open a new terminal for it"
}

Get-Uv | Out-Null

# Three directories under one when -Root is given, their standard places
# otherwise. uv reads the first two, the service reads the third.
if ($Root) {
    $binDir = Join-Path $Root 'bin'
    $env:UV_TOOL_DIR = Join-Path $Root 'tools'
    $env:UV_TOOL_BIN_DIR = $binDir
    if (-not $DataDir) { $DataDir = Join-Path $Root 'data' }
}
else {
    $binDir = & uv tool dir --bin
}
if ($DataDir) {
    [Environment]::SetEnvironmentVariable('VIDEO_TLDR_HOME', $DataDir, 'User')
    $env:VIDEO_TLDR_HOME = $DataDir
}

$chosen = Resolve-Extra
Write-Step "Installing $PackageName with the $chosen extra"

$release = Get-Release
Write-Step "Release $($release.tag_name)"

$staging = Join-Path ([System.IO.Path]::GetTempPath()) "video-tldr-install-$PID"
New-Item -ItemType Directory -Path $staging -Force | Out-Null
try {
    $wheel = Save-Asset $release '*.whl' $staging
    # Both files come from the release rather than from this script: the
    # overrides keep faster-whisper from pulling the CPU onnxruntime in
    # next to the GPU one, where the two overwrite each other's DLLs, and
    # the constraints pin the combination the release was tested with.
    $overrides = Save-Asset $release 'overrides.txt' $staging
    $constraints = Save-Asset $release "constraints-$chosen.txt" $staging

    Stop-RunningService $binDir

    $requirement = "$PackageName[$chosen] @ $(([System.Uri]$wheel).AbsoluteUri)"
    & uv tool install --force --overrides $overrides --constraints $constraints $requirement
    if ($LASTEXITCODE -ne 0) { throw "uv tool install failed with $LASTEXITCODE" }
}
finally {
    Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
}

Add-ToUserPath $binDir

$installed = Join-Path $binDir 'video-tldr.exe'
& $installed --version
Write-Step 'Done. `video-tldr probe` checks the tools, `video-tldr serve` starts it.'
Write-Step 'The speech models download on first use, several gigabytes.'
