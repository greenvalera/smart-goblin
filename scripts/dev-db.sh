#!/usr/bin/env bash
#
# Manage Smart Goblin development database
#
# Usage:
#   ./dev-db.sh start           Start the development database
#   ./dev-db.sh stop            Stop the development database
#   ./dev-db.sh reset           Remove the database volume and start fresh
#   ./dev-db.sh status          Show container status
#   ./dev-db.sh logs            Show database logs
#   ./dev-db.sh start --pgadmin Start with pgAdmin web interface

set -euo pipefail

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.dev.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info() {
    echo -e "${CYAN}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is running
check_docker() {
    if ! docker info &>/dev/null; then
        error "Docker is not running. Please start Docker."
        exit 1
    fi
}

# Build compose command args
get_compose_args() {
    local args=("-f" "$COMPOSE_FILE")
    if [[ "${WITH_PGADMIN:-false}" == "true" ]]; then
        args+=("--profile" "tools")
    fi
    echo "${args[@]}"
}

usage() {
    echo "Usage: $0 {start|stop|reset|status|logs} [--pgadmin]"
    echo ""
    echo "Commands:"
    echo "  start     Start the development database"
    echo "  stop      Stop the development database"
    echo "  reset     Remove the database volume and start fresh"
    echo "  status    Show container status"
    echo "  logs      Show database logs (follow mode)"
    echo ""
    echo "Options:"
    echo "  --pgadmin  Include pgAdmin web interface (for start command)"
    exit 1
}

cmd_start() {
    check_docker
    info "Starting development database..."

    local compose_args
    compose_args=$(get_compose_args)
    # shellcheck disable=SC2086
    docker compose $compose_args up -d

    success "Development database is running on localhost:5432"
    info "Connection URL: postgresql+asyncpg://goblin:password@localhost:5432/smart_goblin"

    if [[ "${WITH_PGADMIN:-false}" == "true" ]]; then
        info "pgAdmin available at: http://localhost:5050"
    fi
}

cmd_stop() {
    check_docker
    info "Stopping development database..."

    local compose_args
    compose_args=$(get_compose_args)
    # shellcheck disable=SC2086
    docker compose $compose_args down

    success "Development database stopped"
}

cmd_reset() {
    check_docker
    info "Resetting development database..."
    info "This will delete all data in the development database."

    read -rp "Are you sure? (y/N) " confirmation
    if [[ "$confirmation" != "y" && "$confirmation" != "Y" ]]; then
        info "Reset cancelled"
        exit 0
    fi

    local compose_args
    compose_args=$(get_compose_args)

    # Stop containers and remove volumes
    # shellcheck disable=SC2086
    docker compose $compose_args down -v

    # Start fresh
    info "Starting fresh database..."
    # shellcheck disable=SC2086
    docker compose $compose_args up -d

    success "Development database has been reset and is running"
    info "Connection URL: postgresql+asyncpg://goblin:password@localhost:5432/smart_goblin"
}

cmd_status() {
    check_docker
    info "Development database status:"
    docker compose -f "$COMPOSE_FILE" ps
}

cmd_logs() {
    check_docker
    info "Database logs (Ctrl+C to exit):"
    docker compose -f "$COMPOSE_FILE" logs -f db
}

# Parse arguments
COMMAND="${1:-}"
WITH_PGADMIN="false"

# Check for --pgadmin flag
for arg in "$@"; do
    if [[ "$arg" == "--pgadmin" ]]; then
        WITH_PGADMIN="true"
    fi
done

case "$COMMAND" in
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    reset)
        cmd_reset
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    *)
        usage
        ;;
esac
