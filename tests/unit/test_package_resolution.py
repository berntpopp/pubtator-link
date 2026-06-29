"""Packaging guardrails for supported runtime dependencies."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _project_metadata() -> dict[str, object]:
    return tomllib.loads(Path("pyproject.toml").read_text())["project"]


def test_project_requires_python_312_or_newer() -> None:
    metadata = _project_metadata()

    assert metadata["requires-python"] == ">=3.12"


def test_modern_mcp_dependencies_are_declared() -> None:
    metadata = _project_metadata()
    deps = list(metadata["dependencies"])
    dependencies = "\n".join(deps)

    # mcp[cli]'s lower bound advances via Dependabot; assert the bounded 1.x
    # range rather than an exact floor so version bumps don't break CI.
    assert any(d.startswith("mcp[cli]>=1.") and d.endswith(",<2.0.0") for d in deps), deps
    assert "fastmcp>=3.2.0,<4.0.0" in dependencies
    assert "fastapi>=0.115.0,<1.0.0" in dependencies
