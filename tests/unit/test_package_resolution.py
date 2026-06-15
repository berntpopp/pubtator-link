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
    dependencies = "\n".join(metadata["dependencies"])

    assert "mcp[cli]>=1.27.2,<2.0.0" in dependencies
    assert "fastmcp>=3.2.0,<4.0.0" in dependencies
    assert "fastapi>=0.115.0,<1.0.0" in dependencies
