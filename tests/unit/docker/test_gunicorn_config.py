from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

CONFIG = Path("docker/gunicorn_conf.py").read_text()


def _load_gunicorn_config() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_gunicorn_conf", "docker/gunicorn_conf.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gunicorn_respects_pubtator_port_and_proxy_headers() -> None:
    assert "PUBTATOR_LINK_PORT" in CONFIG
    assert "forwarded_allow_ips" in CONFIG
    assert "secure_scheme_headers" in CONFIG


def test_gunicorn_worker_count_is_container_safe() -> None:
    assert 'os.environ.get("GUNICORN_WORKERS", "2")' in CONFIG
    assert "max_requests_jitter" in CONFIG


def test_gunicorn_worker_tmp_dir_uses_dev_shm() -> None:
    # Regression test for issue #23: worker heartbeat tempfile must live on a
    # writable tmpfs that survives `read_only: true` containers.
    assert 'worker_tmp_dir = "/dev/shm"' in CONFIG


def test_gunicorn_control_socket_is_disabled_for_read_only_containers() -> None:
    # Regression test for issue #36: Gunicorn 25+ defaults its control socket to
    # $HOME/.gunicorn when XDG_RUNTIME_DIR is unset, which fails under the
    # production read_only filesystem ("Control server error: [Errno 30] ...").
    from gunicorn.config import Config

    module = _load_gunicorn_config()

    # The config file must request the disable...
    assert module.control_socket_disable is True

    # ...and `control_socket_disable` must stay a setting the installed Gunicorn
    # actually honors. Gunicorn silently ignores config-file attributes whose
    # names don't match a known setting, so a future Gunicorn rename/removal
    # would otherwise reintroduce the read-only-filesystem error with no test
    # failing. Validate against the real settings registry to catch that.
    cfg = Config()
    assert "control_socket_disable" in cfg.settings
    cfg.set("control_socket_disable", module.control_socket_disable)
    assert cfg.control_socket_disable is True
