"""Gunicorn configuration for PubTator-Link production deployment."""

from __future__ import annotations

import os
from typing import Any

# Server socket configuration
bind = f"0.0.0.0:{os.environ.get('PUBTATOR_LINK_PORT', os.environ.get('PORT', '8000'))}"
backlog = 2048

# Worker processes configuration
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Worker timeout configuration
timeout = 30
keepalive = 2
graceful_timeout = 30

# Logging configuration
# Use structured logging compatible with PubTator-Link's logging setup
accesslog = "-"  # Log to stdout
errorlog = "-"  # Log to stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
capture_output = True
enable_stdio_inheritance = True

# Process naming
proc_name = "pubtator-link"

# Security settings
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "*")
secure_scheme_headers = {
    "X-FORWARDED-PROTO": "https",
    "X-FORWARDED-SSL": "on",
}

# Performance tuning
preload_app = True
reuse_port = True

# Worker heartbeat tempfile location.
# /dev/shm is a tmpfs that always exists on Linux containers (mode 1777, world-writable),
# so this works under read_only: true root filesystems where /tmp may be unwritable or absent
# for the non-root app user. See issue #23.
worker_tmp_dir = "/dev/shm"

# Gunicorn 25 creates a control socket by default. When XDG_RUNTIME_DIR is unset,
# it falls back to $HOME/.gunicorn, which is unwritable under read_only: true.
control_socket_disable = True


# Graceful handling
def on_starting(server: Any) -> None:
    """Called just before the master process is initialized."""
    server.log.info("Starting PubTator-Link server")


def on_reload(server: Any) -> None:
    """Called to recycle workers during a reload via SIGHUP."""
    server.log.info("Reloading PubTator-Link server")


def worker_int(worker: Any) -> None:
    """Called just after a worker exited on SIGINT or SIGQUIT."""
    worker.log.info("Worker received INT or QUIT signal")


def pre_fork(server: Any, worker: Any) -> None:
    """Called just before a worker is forked."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)


def post_fork(server: Any, worker: Any) -> None:
    """Called just after a worker has been forked."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)


def post_worker_init(worker: Any) -> None:
    """Called just after a worker has initialized the application."""
    worker.log.info("Worker initialized (pid: %s)", worker.pid)


def worker_abort(worker: Any) -> None:
    """Called when a worker received the SIGABRT signal."""
    worker.log.info("Worker aborted (pid: %s)", worker.pid)
