from __future__ import annotations

from pathlib import Path

CONFIG = Path("docker/gunicorn_conf.py").read_text()


def test_gunicorn_respects_pubtator_port_and_proxy_headers() -> None:
    assert "PUBTATOR_LINK_PORT" in CONFIG
    assert "forwarded_allow_ips" in CONFIG
    assert "secure_scheme_headers" in CONFIG


def test_gunicorn_worker_count_is_container_safe() -> None:
    assert 'os.environ.get("GUNICORN_WORKERS", "2")' in CONFIG
    assert "max_requests_jitter" in CONFIG
