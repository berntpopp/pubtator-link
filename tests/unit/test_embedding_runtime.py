"""Contract for the optional CPU-only ONNX embedding runtime (#182)."""

from __future__ import annotations

import asyncio
import os
import tomllib
from pathlib import Path

import pytest

from pubtator_link.services.review_context.embeddings import (
    EmbeddingProviderUnavailableError,
    OnnxEmbeddingProvider,
)

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / ".models" / "bge-small-en-v1.5"


def test_embeddings_extra_is_onnx_and_never_torch() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extra = " ".join(project["project"]["optional-dependencies"]["embeddings"])

    assert "onnxruntime" in extra
    assert "torch" not in extra
    assert "sentence-transformers" not in extra


def test_ci_installs_the_optional_embeddings_runtime() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv sync --group dev --extra embeddings --frozen" in workflow


def test_production_image_bakes_the_runtime_and_pinned_model() -> None:
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")

    assert "--extra embeddings" in dockerfile
    assert "fetch_embedding_model.sh /opt/models/bge-small-en-v1.5" in dockerfile
    assert "PUBTATOR_LINK_REVIEW_EMBEDDING_MODEL_DIR=/opt/models/bge-small-en-v1.5" in dockerfile


def test_missing_model_files_raise_unavailable(tmp_path: Path) -> None:
    with pytest.raises(EmbeddingProviderUnavailableError):
        OnnxEmbeddingProvider(model_dir=str(tmp_path), model_name="m", dim=384)


@pytest.mark.embeddings
def test_baked_model_embeds_normalized_vectors_offline() -> None:
    if not (MODEL_DIR / "model.onnx").is_file():
        pytest.skip("run `make embeddings-model` to fetch the pinned model")
    provider = OnnxEmbeddingProvider(model_dir=str(MODEL_DIR), model_name="m", dim=384)

    query = asyncio.run(provider.embed_query("TBC1D8B nephrotic syndrome"))
    near, far = asyncio.run(
        provider.embed_passages(
            ["TBC1D8B mutations implicate RAB11 trafficking in nephrotic syndrome.", "Pasta."]
        )
    )

    assert len(query) == 384
    assert abs(sum(v * v for v in query) - 1.0) < 1e-4
    dot = lambda a, b: sum(x * y for x, y in zip(a, b, strict=True))  # noqa: E731
    assert dot(query, near) > dot(query, far)


def test_provider_disables_onnxruntime_telemetry_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unset, onnxruntime writes ~/.cache/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db.
    monkeypatch.delenv("ORT_DISABLE_TELEMETRY", raising=False)
    with pytest.raises(EmbeddingProviderUnavailableError):
        OnnxEmbeddingProvider(model_dir=str(tmp_path), model_name="m", dim=384)
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
