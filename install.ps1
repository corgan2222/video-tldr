# Installs the video-tldr service from a GitHub release.
#
#   irm https://raw.githubusercontent.com/corgan2222/video-tldr/main/install.ps1 | iex
#
# The extension is a separate download: the .zip attached to the same
# release, loaded through about:debugging or chrome://extensions.
#
# What this does: pick the extra that fits the machine, stop a running
# service so Windows frees its script, install the wheel with uv, and put
# the shim on the PATH. It registers no autostart and no service: the
# user starts it with `video-tldr serve`, and the extension shows that
# command whenever the service is not answering.

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
    # standard place: ~\.local\bin, uv's tool directory, and
    # %LOCALAPPDATA%\video-tldr for the data.
    [string]$Root,

    # Where config.json, serve.log and the speech models live. Overrides
    # the data directory -Root would choose.
    [string]$DataDir,

    # Register a task that starts the service at every logon, so the
    # extension always finds one. Off by default: a service that runs
    # unasked is the kind of thing a user wants to have chosen.
    # `video-tldr autostart off` takes it back.
    [switch]$Autostart,

    [string]$Repo = 'corgan2222/video-tldr'
)

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 is what a fresh machine has, and it still offers
# TLS 1.0 by default on an untouched install; GitHub answers only 1.2 and
# up, so the download fails with a closed connection and no reason given.
[Net.ServicePointManager]::SecurityProtocol =
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
# Invoke-WebRequest draws a progress bar per chunk in 5.1, which costs more
# than the transfer.
$ProgressPreference = 'SilentlyContinue'

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
    # The name comes from the release answer and decides a path here, so it
    # has to be a bare file name: a separator in it would write outside the
    # staging directory.
    if ($asset.name -ne [IO.Path]::GetFileName($asset.name)) {
        throw "asset name '$($asset.name)' is not a plain file name"
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
#
# `stop` exits 0 whatever it found, so the exit code says nothing about
# what happened; the line it prints does. serve.py answers in one of three
# ways: "service on port N is stopping" when one took the request, "no
# service on port N (...)" when nothing was listening, and "a service on
# port N may still be running, ..." when something is on the port that did
# not confirm the stop. Only the first leaves the machine without a
# service, so only the first raises $askedToStop for the error path below.
#
# The third answer gets no branch of its own here (2026-09-10). It is
# printed, the install goes ahead, and uv is the one that fails on the file
# Windows still holds open, in its own words. A branch would buy a message
# a second earlier for the price of a second wording to keep in step with
# serve.py, and tests/install.test.ts only ties down the one read below.
function Stop-RunningService($binDirectory) {
    $exe = Join-Path $binDirectory 'video-tldr.exe'
    if (-not (Test-Path $exe)) { return }
    Write-Step 'Stopping a running service'
    # 'Continue' for this one call, in a child scope so the setting ends
    # with it: under 'Stop', Windows PowerShell 5.1 turns the first stderr
    # line of a native call into a terminating NativeCommandError. A throw
    # here would end the run with the service down and $askedToStop still
    # $false, so the warning that names the way back would never be shown.
    $said = & {
        $ErrorActionPreference = 'Continue'
        (& $exe stop 2>&1) -join "`n"
    }
    Write-Host $said
    if ($said -match 'is stopping') { $script:askedToStop = $true }
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
$askedToStop = $false
try {
    $wheel = Save-Asset $release '*.whl' $staging
    # Both files come from the release rather than from this script: the
    # overrides keep faster-whisper from pulling the CPU onnxruntime in
    # next to the GPU one, where the two overwrite each other's DLLs, and
    # the constraints pin the combination the release was tested with.
    $overrides = Save-Asset $release 'overrides.txt' $staging
    $constraints = Save-Asset $release "constraints-$chosen.txt" $staging

    # Downloads first, then the stop, then the install. Windows will not let
    # uv replace video-tldr.exe while the process behind it runs, so the stop
    # cannot move behind the install, and a download that fails leaves a
    # running service alone.
    #
    # What remains is a failed install with the service down, and both ways
    # out of that are worse than saying so. Stopping only once the new version
    # stands cannot work: the running shim is the file uv has to overwrite, so
    # the install fails before there is anything new to stop for. Starting the
    # service again in the catch hides the damage: after `uv tool install
    # --force` broke off, the environment behind the shim is whatever uv left
    # there, and a service that answers says nothing about which version it
    # is. So the catch warns, names the way back, and starts nothing.
    Stop-RunningService $binDir

    $requirement = "$PackageName[$chosen] @ $(([System.Uri]$wheel).AbsoluteUri)"
    & uv tool install --force --overrides $overrides --constraints $constraints $requirement
    if ($LASTEXITCODE -ne 0) { throw "uv tool install failed with $LASTEXITCODE" }
}
catch {
    if ($askedToStop) {
        Write-Warning ('The update failed with the service stopped. How much of ' +
            'the installation uv had already replaced is not something this ' +
            'script can tell, so the version from before is not to be counted ' +
            'on: run this installer again to get back to a known one.')
    }
    throw
}
finally {
    Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
}

Add-ToUserPath $binDir

# An update leaves the version it replaced in uv's cache, and these wheels
# run to two gigabytes. Prune drops what nothing references any more, so it
# takes the old one and leaves every other tool's alone.
& uv cache prune | Out-Null

$installed = Join-Path $binDir 'video-tldr.exe'
& $installed --version

if ($Autostart) {
    & $installed autostart on
    if ($LASTEXITCODE -ne 0) { Write-Warning 'autostart could not be registered' }
}

Write-Step 'Done. `video-tldr probe` checks the tools, `video-tldr serve` starts it.'
if (-not $Autostart) {
    Write-Step '`video-tldr autostart on` starts it at every logon instead.'
}
Write-Step 'The speech models download on first use, several gigabytes.'
