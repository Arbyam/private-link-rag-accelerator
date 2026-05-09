# =============================================================================
# Multi-stage Dockerfile for RAG Ingest Worker
# Python 3.12 | Azure Container Apps Job | Non-root user
# =============================================================================

# -----------------------------------------------------------------------------
# Build stage: Install dependencies with uv for fast, reproducible builds
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency files first (layer caching)
COPY pyproject.toml ./

# Create virtual environment and install dependencies
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache .

# -----------------------------------------------------------------------------
# Runtime stage: Minimal image with only runtime dependencies
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Security: Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
COPY src/ ./src/

# Security: Switch to non-root user
USER appuser

# No EXPOSE — this is a Container Apps Job, not a web service

# Run the ingestion worker
CMD ["python", "-m", "src.main"]
