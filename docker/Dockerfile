# Multi-stage Dockerfile for PubTator-Link
# Optimized for both development and production deployment

# --- Builder Stage ---
# This stage installs all dependencies and creates a clean Python environment
FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1 AS builder

# Set environment variables for optimal Python behavior
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install system dependencies required for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment for better dependency isolation
RUN python -m venv /opt/venv
ENV VIRTUAL_ENV="/opt/venv" \
    PATH="/opt/venv/bin:$PATH"

# Copy dependency files first for better layer caching
WORKDIR /app
COPY uv.lock pyproject.toml README.md ./

# F-19: use a digest-pinned uv binary instead of a floating `pip install
# --upgrade pip uv`, so the build toolchain is reproducible and tamper-evident.
COPY --from=ghcr.io/astral-sh/uv:0.8.7@sha256:1e26f9a868360eeb32500a35e05787ffff3402f01a8dc8168ef6aee44aef0aab /uv /usr/local/bin/uv

# Install production dependencies only
RUN uv sync --frozen --no-dev --active

# --- Production Stage ---
# This stage creates the final, minimal production image
FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1 AS production

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    PUBTATOR_LINK_HOST=0.0.0.0 \
    PUBTATOR_LINK_PORT=8000 \
    PUBTATOR_LINK_TRANSPORT=unified \
    TMPDIR=/tmp/pubtator-link

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /tmp/pubtator-link /var/cache/pubtator-link && \
    chown -R app:app /tmp/pubtator-link /var/cache/pubtator-link /home/app

# Copy the virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Set working directory
WORKDIR /home/app/web

# Copy application source code
COPY --chown=app:app ./pubtator_link ./pubtator_link
COPY --chown=app:app ./pyproject.toml ./README.md ./
COPY --chown=app:app ./docker/gunicorn_conf.py ./

# Install the application package
RUN /opt/venv/bin/pip install -e . --no-deps

# Switch to non-root user
USER app

# Expose the application port
EXPOSE 8000

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Default command: the typer CLI boots the unified REST + MCP Streamable HTTP
# server. Production overlays (docker-compose.prod.yml / .npm.yml) override this
# with the hardened multi-worker Gunicorn entrypoint.
CMD ["pubtator-link", "serve", "--transport", "unified", "--host", "0.0.0.0", "--port", "8000"]
