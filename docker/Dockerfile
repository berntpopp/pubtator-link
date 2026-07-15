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
FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1 AS prepared


# Release identity is supplied by the central container-release workflow.
ARG APP_VERSION=0.0.0
ARG VCS_REF=0000000000000000000000000000000000000000
ARG BUILD_DATE=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="PubTator Link" \
      org.opencontainers.image.description="FastAPI and MCP server for PubTator3 biomedical literature research data" \
      org.opencontainers.image.source="https://github.com/berntpopp/pubtator-link" \
      org.opencontainers.image.url="https://github.com/berntpopp/pubtator-link" \
      org.opencontainers.image.documentation="https://github.com/berntpopp/pubtator-link#readme" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="GeneFoundry"
ENV VCS_REF="${VCS_REF}"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    PUBTATOR_LINK_HOST=0.0.0.0 \
    PUBTATOR_LINK_PORT=8000 \
    PUBTATOR_LINK_TRANSPORT=unified \
    TMPDIR=/tmp

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /var/cache/pubtator-link /home/app/.fastmcp && \
    chown -R app:app /var/cache/pubtator-link /home/app

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

RUN rm -rf /root/.cache/pip \
           /usr/local/lib/python*/ensurepip \
           /usr/local/lib/python*/site-packages/pip \
           /usr/local/lib/python*/site-packages/pip-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* \
           /opt/venv/lib/python*/site-packages/pip \
           /opt/venv/lib/python*/site-packages/pip-*.dist-info \
           /opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.* \
           /opt/venv/lib/python*/site-packages/docutils/writers/odf_odt/styles.odt \
    && find / -xdev -type d -name __pycache__ -prune -exec rm -rf '{}' + \
    && find / -xdev -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
RUN find / -xdev -perm /6000 -exec chmod a-s '{}' + \
    && test -z "$(find / -xdev -perm /6000 -print -quit)"
RUN actual="$(find / -xdev -type f -links +1 -printf '%i %p\n' | sort -k2,2)" \
    && expected="$(printf '%s %s\n%s %s\n' \
         "$(stat -c '%i' /usr/bin/perl)" /usr/bin/perl \
         "$(stat -c '%i' /usr/bin/perl5.40.1)" /usr/bin/perl5.40.1 | sort -k2,2)" \
    && { test "$actual" = "$expected" || { printf 'unexpected hardlinks:\n%s\n' "$actual"; exit 1; }; } \
    && rm -f /usr/bin/perl5.40.1

FROM scratch AS production
COPY --from=prepared / /

ARG APP_VERSION=0.0.0
ARG VCS_REF=0000000000000000000000000000000000000000
ARG BUILD_DATE=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="PubTator Link" \
      org.opencontainers.image.description="FastAPI and MCP server for PubTator3 biomedical literature research data" \
      org.opencontainers.image.source="https://github.com/berntpopp/pubtator-link" \
      org.opencontainers.image.url="https://github.com/berntpopp/pubtator-link" \
      org.opencontainers.image.documentation="https://github.com/berntpopp/pubtator-link#readme" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="GeneFoundry"
ENV VCS_REF="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    PUBTATOR_LINK_HOST=0.0.0.0 \
    PUBTATOR_LINK_PORT=8000 \
    PUBTATOR_LINK_TRANSPORT=unified \
    TMPDIR=/tmp
WORKDIR /home/app/web

# Switch to non-root user
USER app

# Expose the application port
EXPOSE 8000

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Default command: the hardened multi-worker Gunicorn entrypoint that drives the
# unified REST + MCP Streamable HTTP ASGI app factory.
#
# The GeneFoundry container-release standard forbids a Compose `command:` override
# on the application service, so the released image must already run the exact
# production process. The `pubtator-link serve` typer CLI (Logging & CLI Standard
# v1) remains the interactive/dev entrypoint and is what docker-compose.yml runs.
CMD ["gunicorn", "-c", "gunicorn_conf.py", "pubtator_link.server_manager:create_app()"]
