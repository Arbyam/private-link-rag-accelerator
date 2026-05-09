# =============================================================================
# Multi-stage Dockerfile for RAG API Service
# Python 3.12 | FastAPI | Non-root user | Azure Container Apps
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

# Container Apps health probe port
EXPOSE 8080

# Health check for orchestrator
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/healthz', timeout=5).raise_for_status()"

# Run FastAPI with uvicorn
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
