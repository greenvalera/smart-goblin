<#
.SYNOPSIS
    Manage Smart Goblin development database

.DESCRIPTION
    Start, stop, or reset the development PostgreSQL database using Docker Compose.

.PARAMETER Command
    The action to perform: start, stop, reset, status, or logs

.EXAMPLE
    .\dev-db.ps1 start
    Start the development database

.EXAMPLE
    .\dev-db.ps1 stop
    Stop the development database

.EXAMPLE
    .\dev-db.ps1 reset
    Remove the database volume and start fresh

.EXAMPLE
    .\dev-db.ps1 start -WithPgAdmin
    Start the database with pgAdmin web interface
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "reset", "status", "logs")]
    [string]$Command = "status",

    [switch]$WithPgAdmin
)

$ErrorActionPreference = "Stop"

# Get project root directory (parent of scripts folder)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "docker-compose.dev.yml"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# Check if Docker is running
function Test-Docker {
    try {
        docker info *>&1 | Out-Null
        return $true
    }
    catch {
        Write-Error "Docker is not running. Please start Docker Desktop."
        return $false
    }
}

# Build docker-compose command with optional pgAdmin profile
function Get-ComposeArgs {
    $args = @("-f", $ComposeFile)
    if ($WithPgAdmin) {
        $args += @("--profile", "tools")
    }
    return $args
}

switch ($Command) {
    "start" {
        if (-not (Test-Docker)) { exit 1 }

        Write-Info "Starting development database..."
        $composeArgs = Get-ComposeArgs
        & docker compose @composeArgs up -d

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Development database is running on localhost:5432"
            Write-Info "Connection URL: postgresql+asyncpg://goblin:password@localhost:5432/smart_goblin"
            if ($WithPgAdmin) {
                Write-Info "pgAdmin available at: http://localhost:5050"
            }
        }
        else {
            Write-Error "Failed to start database"
            exit 1
        }
    }

    "stop" {
        if (-not (Test-Docker)) { exit 1 }

        Write-Info "Stopping development database..."
        $composeArgs = Get-ComposeArgs
        & docker compose @composeArgs down

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Development database stopped"
        }
        else {
            Write-Error "Failed to stop database"
            exit 1
        }
    }

    "reset" {
        if (-not (Test-Docker)) { exit 1 }

        Write-Info "Resetting development database..."
        Write-Info "This will delete all data in the development database."

        $confirmation = Read-Host "Are you sure? (y/N)"
        if ($confirmation -ne "y" -and $confirmation -ne "Y") {
            Write-Info "Reset cancelled"
            exit 0
        }

        # Stop containers and remove volumes
        $composeArgs = Get-ComposeArgs
        & docker compose @composeArgs down -v

        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to remove containers"
            exit 1
        }

        # Start fresh
        Write-Info "Starting fresh database..."
        & docker compose @composeArgs up -d

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Development database has been reset and is running"
            Write-Info "Connection URL: postgresql+asyncpg://goblin:password@localhost:5432/smart_goblin"
        }
        else {
            Write-Error "Failed to start database after reset"
            exit 1
        }
    }

    "status" {
        if (-not (Test-Docker)) { exit 1 }

        Write-Info "Development database status:"
        & docker compose -f $ComposeFile ps
    }

    "logs" {
        if (-not (Test-Docker)) { exit 1 }

        Write-Info "Database logs (Ctrl+C to exit):"
        & docker compose -f $ComposeFile logs -f db
    }
}
