#!/bin/sh
set -e

echo "Running database migrations..."
python -m alembic upgrade head

echo "Starting Smart Goblin bot..."
exec python -m src.main
