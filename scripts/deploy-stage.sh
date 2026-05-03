#!/usr/bin/env bash
#
# Deploy current dev branch to Railway staging and verify the build.
#
# Force-pushes the current branch to `origin/stage` (so Railway redeploys the
# staging environment), then streams the build logs and waits for the bot's
# startup signal in the runtime logs.
#
# Side effect: switches the local Railway CLI link to environment=staging,
# service=smart-goblin. The script does not restore the previous link.
#
# Usage:
#   ./deploy-stage.sh                            Deploy current branch as staging
#   ./deploy-stage.sh --force                    Skip safety guards
#   ./deploy-stage.sh --timeout-minutes 15
#   ./deploy-stage.sh --startup-timeout-seconds 90

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }

FORCE="false"
TIMEOUT_MINUTES=10
STARTUP_TIMEOUT_SECONDS=60

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)
            FORCE="true"
            shift
            ;;
        --timeout-minutes)
            TIMEOUT_MINUTES="$2"
            shift 2
            ;;
        --startup-timeout-seconds)
            STARTUP_TIMEOUT_SECONDS="$2"
            shift 2
            ;;
        -h|--help)
            sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

check_prerequisites() {
    for tool in git railway timeout; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            error "$tool not found in PATH"
            exit 1
        fi
    done

    if ! railway status >/dev/null 2>&1; then
        error "Railway CLI is not linked to a project. Run: railway link"
        exit 1
    fi
}

get_current_branch() {
    git rev-parse --abbrev-ref HEAD 2>/dev/null
}

check_safety_guards() {
    local branch="$1"

    if [[ "$branch" == "main" ]]; then
        error "Refusing to deploy 'main' as staging. Use the release flow (PR into main) for production."
        exit 1
    fi

    local dirty
    dirty="$(git status --porcelain)"
    if [[ -n "$dirty" ]]; then
        error "Working tree is dirty. Commit or stash your changes first:"
        echo "$dirty"
        exit 1
    fi

    info "Fetching origin/$branch to verify HEAD is pushed..."
    if ! git fetch origin "$branch" >/dev/null 2>&1; then
        error "Branch '$branch' has no remote at origin. Push it first: git push -u origin $branch"
        exit 1
    fi

    local local_sha remote_sha
    local_sha="$(git rev-parse HEAD)"
    remote_sha="$(git rev-parse "origin/$branch")"
    if [[ "$local_sha" != "$remote_sha" ]]; then
        error "Local HEAD ($local_sha) differs from origin/$branch ($remote_sha). Push your dev branch first so stage doesn't hold orphan code."
        exit 1
    fi
}

switch_railway_to_staging() {
    info "Switching Railway link to environment=staging, service=smart-goblin..."
    railway environment staging
    railway service smart-goblin
}

push_to_stage() {
    local branch="$1"
    info "Force-pushing $branch -> origin/stage (--force-with-lease)..."
    git fetch origin stage >/dev/null 2>&1 || true
    git push origin "${branch}:stage" --force-with-lease
    success "Pushed $branch to origin/stage"
}

wait_build_complete() {
    info "Waiting 10s for Railway to register the new deployment..."
    sleep 10

    local timeout_secs=$((TIMEOUT_MINUTES * 60))
    info "Streaming build logs (will exit when build finishes; timeout ${TIMEOUT_MINUTES}m)..."

    local rc=0
    timeout "$timeout_secs" railway logs --build || rc=$?

    if [[ $rc -eq 124 ]]; then
        error "Build did not finish within ${TIMEOUT_MINUTES}m"
        exit 1
    elif [[ $rc -ne 0 ]]; then
        error "Build failed (exit code $rc) — see logs above"
        exit 1
    fi

    success "Build phase finished"
}

wait_app_startup() {
    info "Waiting 5s for app container to start..."
    sleep 5

    info "Tailing runtime logs for up to ${STARTUP_TIMEOUT_SECONDS}s, looking for: 'Bot is now polling for updates'..."

    local rc=0
    timeout "$STARTUP_TIMEOUT_SECONDS" bash -c '
        railway logs 2>&1 | while IFS= read -r line; do
            echo "$line"
            if [[ "$line" == *"Bot is now polling for updates"* ]]; then
                exit 0
            fi
        done
        exit 1
    ' || rc=$?

    case $rc in
        0)   return 0 ;;
        124) return 1 ;;
        *)   return 1 ;;
    esac
}

# Main

check_prerequisites

BRANCH="$(get_current_branch || true)"
if [[ -z "$BRANCH" || "$BRANCH" == "HEAD" ]]; then
    error "Not in a git repository (or detached HEAD)"
    exit 1
fi
info "Current branch: $BRANCH"

if [[ "$FORCE" != "true" ]]; then
    check_safety_guards "$BRANCH"
else
    warn "Skipping safety guards (--force)"
fi

switch_railway_to_staging
push_to_stage "$BRANCH"
wait_build_complete

if wait_app_startup; then
    success "Staging deploy successful — bot is polling for updates"
    exit 0
else
    warn "Build OK but startup signal not seen within ${STARTUP_TIMEOUT_SECONDS}s. Check the staging Telegram bot manually."
    exit 0
fi
