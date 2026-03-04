# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Production image
FROM python:3.11-slim

WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY src/ src/
COPY migrations/ migrations/
COPY alembic.ini .
COPY scripts/ scripts/

# Create non-root user
RUN useradd --create-home appuser
USER appuser

CMD ["sh", "scripts/start.sh"]
