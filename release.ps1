<#
.SYNOPSIS
    Cut a new release of fm-saxml-converter.

.DESCRIPTION
    1. Pre-flight: tools present, on master, clean tree, in sync with origin.
    2. Prompt for MAJOR.MINOR.PATCH and make sure it is valid, newer than the
       latest tag, and unused (local tag, remote tag, GitHub Release, PyPI).
    3. Set __version__ in src/fm_saxml/__init__.py.
    4. Run the test suite, build sdist + wheel, twine check, and smoke-test the
       wheel in a throwaway venv (--version must match, doctor must pass).
    5. After confirmation: commit the bump, push master, wait for CI to pass,
       push an annotated vX.Y.Z tag and follow the Release workflow (which
       builds the executables, creates the GitHub Release and publishes to PyPI).

    Requires: git, uv, and gh (authenticated) for the CI/release steps.

.PARAMETER DryRun
    Run every check, test and build, but commit, tag and push nothing.

.PARAMETER Version
    The version to release. Prompted for when omitted.

.EXAMPLE
    .\release.ps1
.EXAMPLE
    .\release.ps1 -DryRun -Version 0.5.0
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$Version
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Package = 'fm-saxml-converter'
$MainBranch = 'master'
$Remote = 'origin'
$VersionFile = Join-Path $PSScriptRoot 'src\fm_saxml\__init__.py'
$VersionPattern = '(?m)^__version__ = "(.*)"'

Set-Location $PSScriptRoot

# ---------------------------------------------------------------- helpers

function Write-Step([string]$Message) { Write-Host ''; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host '  ok ' -ForegroundColor Green -NoNewline; Write-Host $Message }
function Write-Warn([string]$Message) { Write-Host '  warning: ' -ForegroundColor Yellow -NoNewline; Write-Host $Message }

class ReleaseAbort : System.Exception {
    ReleaseAbort([string]$Message) : base($Message) {}
}
function Stop-Release([string]$Message) { throw [ReleaseAbort]::new($Message) }

# Run a native command, echoing its output; abort if it exits non-zero.
function Invoke-Native([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        Stop-Release "'$Command $($Arguments -join ' ')' failed (exit $LASTEXITCODE)."
    }
}

# Run a native command quietly and return its trimmed stdout, or $null on failure.
# Stderr is discarded; EAP is relaxed so Windows PowerShell 5.1 doesn't turn it into an error.
function Get-NativeOutput([string]$Command, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Command @Arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return (($out | Out-String).Trim())
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Test-Native([string]$Command, [string[]]$Arguments) {
    return ($null -ne (Get-NativeOutput $Command $Arguments))
}

function Confirm-Step([string]$Question) {
    $reply = Read-Host "$Question [y/N]"
    return ($reply -match '^(y|yes)$')
}

function Get-CurrentVersion {
    $match = [regex]::Match((Get-Content -Raw $VersionFile), $VersionPattern)
    if ($match.Success) { return $match.Groups[1].Value }
    return $null
}

# Write text as UTF-8 without a BOM, keeping its line endings as they are.
function Set-FileText([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false))
}

function Get-PypiStatus([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -Method Head -UseBasicParsing -TimeoutSec 20
        return [int]$response.StatusCode
    } catch {
        $response = $_.Exception.Response
        if ($null -ne $response) { return [int]$response.StatusCode }
        return 0
    }
}

# Find the workflow run for a commit; GitHub can take a few seconds to register it.
function Find-WorkflowRun([string]$Workflow, [string]$Sha) {
    for ($i = 0; $i -lt 30; $i++) {
        $id = Get-NativeOutput 'gh' @('run', 'list', '--workflow', $Workflow, '--commit', $Sha,
            '--limit', '1', '--json', 'databaseId', '--jq', '.[0].databaseId // empty')
        if ($id) { return $id }
        Start-Sleep -Seconds 5
    }
    return $null
}

$originalVersionText = $null
$bumpCommitted = $false
$workDir = $null

try {
    # ------------------------------------------------------------ 1. pre-flight

    Write-Step 'Pre-flight checks'

    foreach ($tool in 'git', 'uv') {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Stop-Release "'$tool' is not on PATH." }
    }

    $haveGh = $false
    if ((Get-Command gh -ErrorAction SilentlyContinue) -and (Test-Native 'gh' @('auth', 'status'))) {
        $haveGh = $true
        Write-Ok 'gh is installed and authenticated'
    } elseif ($DryRun) {
        Write-Warn 'gh is missing or not logged in; skipping the GitHub Release check.'
    } else {
        Stop-Release 'gh must be installed and logged in (run: gh auth login).'
    }

    $branch = Get-NativeOutput 'git' @('rev-parse', '--abbrev-ref', 'HEAD')
    if ($branch -ne $MainBranch) { Stop-Release "On branch '$branch'; releases are cut from '$MainBranch'." }
    Write-Ok "on $MainBranch"

    $status = Get-NativeOutput 'git' @('status', '--porcelain')
    if ($status) {
        if ($DryRun) {
            Write-Warn 'working tree has uncommitted changes (allowed in -DryRun).'
        } else {
            Write-Host $status
            Stop-Release 'Working tree is not clean. Commit or stash the changes above first.'
        }
    } else {
        Write-Ok 'working tree clean'
    }

    if (-not (Test-Native 'git' @('fetch', '--quiet', '--tags', $Remote, $MainBranch))) {
        Stop-Release "git fetch from $Remote failed."
    }
    $localSha = Get-NativeOutput 'git' @('rev-parse', 'HEAD')
    $remoteSha = Get-NativeOutput 'git' @('rev-parse', "$Remote/$MainBranch")
    if ($localSha -ne $remoteSha) {
        if (Test-Native 'git' @('merge-base', '--is-ancestor', $localSha, $remoteSha)) {
            Stop-Release "Local $MainBranch is behind $Remote/$MainBranch. Pull first."
        } elseif (-not (Test-Native 'git' @('merge-base', '--is-ancestor', $remoteSha, $localSha))) {
            Stop-Release "Local $MainBranch has diverged from $Remote/$MainBranch."
        }
        Write-Warn "local $MainBranch has unpushed commits; they will be pushed with the release."
    } else {
        Write-Ok "in sync with $Remote/$MainBranch"
    }

    # ------------------------------------------------------------ 2. version

    Write-Step 'Version'

    $current = Get-CurrentVersion
    if (-not $current) { Stop-Release "Could not read __version__ from $VersionFile." }

    $latestTag = $null
    $tags = Get-NativeOutput 'git' @('tag', '-l', 'v*')
    if ($tags) {
        $latestTag = $tags -split "`r?`n" |
            ForEach-Object { $_.Trim() -replace '^v', '' } |
            Where-Object { $_ -match '^\d+\.\d+\.\d+$' } |
            Sort-Object { [version]$_ } |
            Select-Object -Last 1
    }
    Write-Host "  __version__ in source: $current"
    Write-Host "  latest release tag:    $(if ($latestTag) { "v$latestTag" } else { '(none)' })"

    if (-not $Version) { $Version = Read-Host 'New version (MAJOR.MINOR.PATCH)' }
    $Version = ($Version -replace '\s', '') -replace '^v', ''

    if ($Version -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$') {
        Stop-Release "'$Version' is not a valid MAJOR.MINOR.PATCH version (e.g. 1.2.3)."
    }
    Write-Ok "$Version is well formed"

    if ($latestTag) {
        if ([version]$Version -le [version]$latestTag) {
            Stop-Release "$Version is not newer than the latest release v$latestTag."
        }
        Write-Ok "newer than v$latestTag"
    }

    $tag = "v$Version"

    if (Test-Native 'git' @('rev-parse', '-q', '--verify', "refs/tags/$tag")) {
        Stop-Release "Tag $tag already exists locally."
    }
    if (Get-NativeOutput 'git' @('ls-remote', '--tags', $Remote, "refs/tags/$tag")) {
        Stop-Release "Tag $tag already exists on $Remote."
    }
    Write-Ok "tag $tag is unused"

    if ($haveGh) {
        if (Test-Native 'gh' @('release', 'view', $tag)) { Stop-Release "A GitHub Release named $tag already exists." }
        Write-Ok "no GitHub Release $tag"
    }

    $pypiStatus = Get-PypiStatus "https://pypi.org/pypi/$Package/$Version/json"
    switch ($pypiStatus) {
        200 { Stop-Release "$Package $Version is already on PyPI (versions can never be reused)." }
        404 { Write-Ok "$Version is not on PyPI" }
        default { Stop-Release "Could not check PyPI (HTTP $pypiStatus). Check your connection and retry." }
    }

    # ------------------------------------------------------------ 3. bump

    Write-Step "Setting __version__ to $Version"

    $needsBump = ($current -ne $Version)
    if ($needsBump) {
        $originalVersionText = Get-Content -Raw $VersionFile
        $updated = [regex]::Replace($originalVersionText, $VersionPattern, "__version__ = `"$Version`"")
        Set-FileText $VersionFile $updated
        if ((Get-CurrentVersion) -ne $Version) { Stop-Release "Failed to update $VersionFile." }
        Write-Ok "src/fm_saxml/__init__.py updated ($current -> $Version)"
    } else {
        Write-Ok "src/fm_saxml/__init__.py already says $Version; no bump needed"
    }

    # ------------------------------------------------------------ 4. test & build

    Write-Step 'Syncing environment'
    Invoke-Native 'uv' @('sync', '--extra', 'dev')

    Write-Step 'Running tests'
    Invoke-Native 'uv' @('run', '--extra', 'dev', 'python', '-m', 'pytest', '-q')

    Write-Step 'Building sdist and wheel'
    $workDir = Join-Path ([System.IO.Path]::GetTempPath()) "fm-saxml-release-$([guid]::NewGuid().ToString('N'))"
    $distDir = Join-Path $workDir 'dist'
    Invoke-Native 'uv' @('build', '--out-dir', $distDir)
    $artifacts = @(Get-ChildItem $distDir -File |
        Where-Object { $_.Name -like '*.whl' -or $_.Name -like '*.tar.gz' } |
        ForEach-Object { $_.FullName })
    $artifacts | ForEach-Object { Write-Host "  $(Split-Path $_ -Leaf)" }

    Write-Step 'Checking package metadata'
    Invoke-Native 'uvx' (@('twine', 'check', '--strict') + $artifacts)

    Write-Step 'Smoke-testing the wheel in a clean venv'
    $wheel = $artifacts | Where-Object { $_ -like '*.whl' } | Select-Object -First 1
    $venvDir = Join-Path $workDir 'venv'
    Invoke-Native 'uv' @('venv', '--quiet', $venvDir)
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'
    $venvCli = Join-Path $venvDir 'Scripts\fm-saxml.exe'
    if (-not (Test-Path $venvPython)) {
        $venvPython = Join-Path $venvDir 'bin/python'
        $venvCli = Join-Path $venvDir 'bin/fm-saxml'
    }
    Invoke-Native 'uv' @('pip', 'install', '--quiet', '--python', $venvPython, $wheel)
    $reported = Get-NativeOutput $venvCli @('--version')
    if (-not $reported -or -not $reported.EndsWith($Version)) {
        Stop-Release "Installed CLI reports '$reported', expected $Version."
    }
    Write-Ok "fm-saxml --version -> $reported"
    $env:FM_SAXML_NO_UPDATE_CHECK = '1'
    try { Invoke-Native $venvCli @('doctor') } finally { Remove-Item Env:FM_SAXML_NO_UPDATE_CHECK }
    Write-Ok 'fm-saxml doctor passed'

    if ($DryRun) {
        Write-Step 'Dry run complete'
        Write-Host "Every check passed for $Version. Nothing was committed, tagged or pushed."
        return
    }

    # ------------------------------------------------------------ 5. publish

    Write-Step "Ready to release $tag"
    Write-Host '  This will:'
    if ($needsBump) { Write-Host "    - commit the version bump on $MainBranch" }
    Write-Host "    - push $MainBranch to $Remote and wait for CI"
    Write-Host "    - create and push tag $tag, which triggers the Release workflow"
    Write-Host '      (executables, GitHub Release and PyPI publish if enabled)'
    Write-Host "  PyPI releases are permanent; $Version can never be re-uploaded." -ForegroundColor Yellow
    if (-not (Confirm-Step 'Proceed?')) { Stop-Release 'Aborted. Nothing was pushed.' }

    if ($needsBump) {
        Invoke-Native 'git' @('add', 'src/fm_saxml/__init__.py')
        Invoke-Native 'git' @('commit', '--quiet', '-m', "Version bump to $Version")
        $bumpCommitted = $true
        Write-Ok 'committed version bump'
    }

    $releaseSha = Get-NativeOutput 'git' @('rev-parse', 'HEAD')
    $shortSha = $releaseSha.Substring(0, 7)
    Invoke-Native 'git' @('push', $Remote, $MainBranch)
    Write-Ok "pushed $MainBranch"

    Write-Step "Waiting for CI on $shortSha"
    $ciRun = Find-WorkflowRun 'ci.yml' $releaseSha
    if (-not $ciRun) {
        Stop-Release "No CI run appeared for $shortSha. Check the Actions tab, then tag manually: git tag -a $tag -m $tag; git push $Remote $tag"
    }
    & gh run watch $ciRun --exit-status --interval 15
    if ($LASTEXITCODE -ne 0) {
        Stop-Release "CI failed (run $ciRun). Not tagging. Fix it, then rerun this script with the same version."
    }
    Write-Ok 'CI passed'

    Write-Step "Tagging $tag"
    Invoke-Native 'git' @('tag', '-a', $tag, '-m', "Release $tag", $releaseSha)
    Invoke-Native 'git' @('push', $Remote, $tag)
    Write-Ok "pushed $tag"

    Write-Step 'Following the Release workflow'
    $releaseRun = Find-WorkflowRun 'release.yml' $releaseSha
    if (-not $releaseRun) { Stop-Release 'No Release run appeared. Check the Actions tab.' }
    & gh run watch $releaseRun --exit-status --interval 20
    if ($LASTEXITCODE -ne 0) {
        Write-Host ''
        Write-Host "The Release workflow failed (run $releaseRun): gh run view $releaseRun --log-failed"
        Write-Host 'If nothing reached PyPI yet, you can delete the tag and retry:'
        Write-Host "  git tag -d $tag; git push $Remote :refs/tags/$tag"
        exit 1
    }

    Write-Step "Released $tag"
    $releaseUrl = Get-NativeOutput 'gh' @('release', 'view', $tag, '--json', 'url', '--jq', '.url')
    if ($releaseUrl) { Write-Host "GitHub: $releaseUrl" }
    Write-Host "PyPI:   https://pypi.org/project/$Package/$Version/"
    Write-Host '(The PyPI job only runs when the PUBLISH_TO_PYPI repo variable is "true".)'
} catch [ReleaseAbort] {
    Write-Host "error: $($_.Exception.Message)" -ForegroundColor Red
    $global:LASTEXITCODE = 1
    exit 1
} finally {
    if ($null -ne $originalVersionText -and -not $bumpCommitted) {
        Set-FileText $VersionFile $originalVersionText
        Write-Host 'Restored src/fm_saxml/__init__.py.'
    }
    if ($workDir -and (Test-Path $workDir)) {
        Remove-Item -Recurse -Force $workDir -ErrorAction SilentlyContinue
    }
}
