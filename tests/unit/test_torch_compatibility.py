"""Compatibility contract for the optional CPU embedding runtime."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_embeddings_constraint_requires_torch_2_13() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"torch>=2.13.0"' in project


def test_ci_installs_the_optional_embeddings_runtime() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv sync --group dev --extra embeddings --frozen" in workflow


@pytest.mark.embeddings
def test_embeddings_extra_imports_torch_2_13_on_cpu() -> None:
    torch = importlib.import_module("torch")
    importlib.import_module("sentence_transformers")

    assert torch.__version__.split("+", maxsplit=1)[0] == "2.13.0"
    assert torch.tensor([1.0, 2.0]).device.type == "cpu"
