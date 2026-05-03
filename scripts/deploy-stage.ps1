<#
.SYNOPSIS
    Deploy current dev branch to Railway staging and verify the build.

.DESCRIPTION
    Force-pushes the current branch to `origin/stage` (so Railway redeploys the
    staging environment), then streams the build logs and waits for the bot's
    startup signal in the runtime logs.

    Side effect: switches the local Railway CLI link to environment=staging,
    service=smart-goblin. The script does not restore the previous link.

.PARAMETER Force
    Skip pre-flight safety guards (HEAD != main, clean working tree,
    HEAD pushed to origin). Use only when you know what you're doing.

.PARAMETER TimeoutMinutes
    Maximum minutes to wait for the build phase to complete. Default: 10.

.PARAMETER StartupTimeoutSeconds
    Maximum seconds to wait for the bot's startup signal in runtime logs after
    a successful build. Default: 60.

.EXAMPLE
    .\deploy-stage.ps1
    Deploy the current branch as staging.

.EXAMPLE
    .\deploy-stage.ps1 -Force
    Deploy bypassing safety guards.
#>

param(
    [switch]$Force,
    [int]$TimeoutMinutes = 10,
    [int]$StartupTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Test-Prerequisites {
    foreach ($tool in @('git', 'railway')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            Write-Err "$tool not found in PATH"
            return $false
        }
    }

    & railway status | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Railway CLI is not linked to a project. Run: railway link"
        return $false
    }

    return $true
}

function Get-CurrentBranch {
    $branch = & git rev-parse --abbrev-ref HEAD 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return $branch.Trim()
}

function Test-SafetyGuards {
    param([string]$Branch)

    if ($Branch -eq 'main') {
        Write-Err "Refusing to deploy 'main' as staging. Use the release flow (PR into main) for production."
        return $false
    }

    $dirty = & git status --porcelain
    if ($LASTEXITCODE -ne 0) {
        Write-Err "git status failed"
        return $false
    }
    if ($dirty) {
        Write-Err "Working tree is dirty. Commit or stash your changes first:"
        Write-Host $dirty
        return $false
    }

    Write-Info "Fetching origin/$Branch to verify HEAD is pushed..."
    & git fetch --quiet origin $Branch
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Branch '$Branch' has no remote at origin. Push it first: git push -u origin $Branch"
        return $false
    }

    $localSha = (& git rev-parse HEAD).Trim()
    $remoteSha = (& git rev-parse "origin/$Branch").Trim()
    if ($localSha -ne $remoteSha) {
        Write-Err "Local HEAD ($localSha) differs from origin/$Branch ($remoteSha). Push your dev branch first so stage doesn't hold orphan code."
        return $false
    }

    return $true
}

function Switch-RailwayToStaging {
    Write-Info "Switching Railway link to environment=staging, service=smart-goblin..."
    & railway environment staging
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed to switch to staging environment"
        return $false
    }
    & railway service smart-goblin
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed to link smart-goblin service"
        return $false
    }
    return $true
}

function Invoke-StagePush {
    param([string]$Branch)

    Write-Info "Force-pushing $Branch -> origin/stage (--force-with-lease)..."
    & git fetch --quiet origin stage
    & git push origin "${Branch}:stage" --force-with-lease
    if ($LASTEXITCODE -ne 0) {
        Write-Err "git push failed"
        return $false
    }
    Write-Success "Pushed $Branch to origin/stage"
    return $true
}

function Wait-DeploymentRegistered {
    param(
        [string]$ExpectedCommitHash,
        [int]$TimeoutSeconds = 60
    )

    $shortSha = $ExpectedCommitHash.Substring(0, 7)
    Write-Info "Locating Railway deployment for commit ${shortSha}..."
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        $json = & railway deployment list --json --limit 5
        if ($LASTEXITCODE -eq 0 -and $json) {
            try {
                $deployments = $json | ConvertFrom-Json
                $match = $deployments | Where-Object { $_.meta.commitHash -eq $ExpectedCommitHash } | Select-Object -First 1
                if ($match) {
                    Write-Info "Found deployment $($match.id) (status: $($match.status))"
                    return $match.id
                }
            }
            catch {
                Write-Warn "Failed to parse deployment list JSON: $_"
            }
        }
        Start-Sleep -Seconds 3
    }

    Write-Err "Railway did not register a deployment for commit ${ExpectedCommitHash} within ${TimeoutSeconds}s"
    return $null
}

function Wait-BuildComplete {
    param([int]$TimeoutMinutes, [string]$DeploymentId)

    Write-Info "Streaming build logs for deployment ${DeploymentId} (timeout ${TimeoutMinutes}m)..."

    $job = Start-Job -ArgumentList $DeploymentId -ScriptBlock {
        param($id)
        & railway logs --build $id 2>&1
    }

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $timedOut = $false

    while ($job.State -eq 'Running') {
        if ((Get-Date) -gt $deadline) {
            $timedOut = $true
            break
        }
        $chunk = Receive-Job -Job $job -ErrorAction SilentlyContinue
        if ($chunk) { $chunk | ForEach-Object { Write-Host $_ } }
        Start-Sleep -Milliseconds 500
    }

    if ($timedOut) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        Write-Err "Build did not finish within ${TimeoutMinutes}m"
        return $false
    }

    $tail = Receive-Job -Job $job -ErrorAction SilentlyContinue
    if ($tail) { $tail | ForEach-Object { Write-Host $_ } }
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue

    Write-Success "Build phase finished"
    return $true
}

function Wait-AppStartup {
    param([int]$TimeoutSeconds, [string]$DeploymentId)

    Write-Info "Waiting 5s for app container to start..."
    Start-Sleep -Seconds 5

    Write-Info "Polling runtime logs for deployment ${DeploymentId} (up to ${TimeoutSeconds}s), looking for: 'Bot is now polling for updates'..."

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $found = $false

    while ((Get-Date) -lt $deadline) {
        $output = & railway logs $DeploymentId -n 200
        if ($output) {
            foreach ($line in $output) {
                if ($line -match 'Bot is now polling for updates') {
                    Write-Host $line
                    $found = $true
                    break
                }
            }
        }
        if ($found) { break }
        Start-Sleep -Seconds 5
    }

    return $found
}

# Main

if (-not (Test-Prerequisites)) { exit 1 }

$branch = Get-CurrentBranch
if (-not $branch) {
    Write-Err "Not in a git repository (or detached HEAD)"
    exit 1
}
Write-Info "Current branch: $branch"

if (-not $Force) {
    if (-not (Test-SafetyGuards -Branch $branch)) {
        Write-Info "Use -Force to bypass safety guards (not recommended)."
        exit 1
    }
}
else {
    Write-Warn "Skipping safety guards (-Force)"
}

if (-not (Switch-RailwayToStaging)) { exit 1 }
if (-not (Invoke-StagePush -Branch $branch)) { exit 1 }

$ourSha = (& git rev-parse HEAD).Trim()
$deploymentId = Wait-DeploymentRegistered -ExpectedCommitHash $ourSha
if (-not $deploymentId) { exit 1 }

if (-not (Wait-BuildComplete -TimeoutMinutes $TimeoutMinutes -DeploymentId $deploymentId)) { exit 1 }

if (Wait-AppStartup -TimeoutSeconds $StartupTimeoutSeconds -DeploymentId $deploymentId) {
    Write-Success "Staging deploy successful - bot is polling for updates"
    exit 0
}
else {
    Write-Warn "Build OK but startup signal not seen within ${StartupTimeoutSeconds}s. Check the staging Telegram bot manually."
    exit 0
}
