from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Protocol, cast

ENCODE_BATCH = 8
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingProviderUnavailableError(RuntimeError):
    """Raised when optional embedding dependencies are not installed."""


class EmbeddingProvider(Protocol):
    model_name: str
    dim: int

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_passages(self, texts: list[str]) -> list[list[float]]: ...


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bge_query_text(text: str) -> str:
    return f"{BGE_QUERY_PREFIX}{text}"


def bge_passage_text(text: str) -> str:
    return text


class FakeEmbeddingProvider:
    def __init__(self, *, dim: int, model_name: str = "fake-embedding") -> None:
        self.model_name = model_name
        self.dim = dim

    async def embed_query(self, text: str) -> list[float]:
        return self._embed_one(bge_query_text(text))

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(bge_passage_text(text)) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        counter = 0
        while len(values) < self.dim:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            counter += 1
        return values[: self.dim]


class OnnxEmbeddingProvider:
    """CPU-only BGE-style encoder (CLS pooling, L2-normalized) on onnxruntime.

    Loads ``model.onnx`` + ``tokenizer.json`` from ``model_dir`` eagerly, so a missing
    extra or missing model files raise ``EmbeddingProviderUnavailableError`` at
    construction instead of on the first request. Never touches the network.
    """

    def __init__(
        self,
        *,
        model_dir: str,
        model_name: str,
        dim: int,
        max_length: int = 512,
        threads: int = 2,
    ) -> None:
        self.model_name = model_name
        self.dim = dim
        # onnxruntime otherwise writes a usage DB to ~/.cache/Microsoft/DeveloperTools (a
        # write on a read-only rootfs, and a file the image content gate rejects).
        os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise EmbeddingProviderUnavailableError(
                "Install the 'embeddings' extra (onnxruntime, tokenizers, numpy)."
            ) from exc
        model_path = Path(model_dir) / "model.onnx"
        tokenizer_path = Path(model_dir) / "tokenizer.json"
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise EmbeddingProviderUnavailableError(
                "Embedding model files are missing; run `make embeddings-model`."
            )
        self._np = np
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
        tokenizer.enable_truncation(max_length=max_length)
        tokenizer.enable_padding()
        self._tokenizer = tokenizer
        options = ort.SessionOptions()
        # ORT defaults to every host core, ignoring the container CPU quota.
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
        self._input_names = {item.name for item in self._session.get_inputs()}

    async def embed_query(self, text: str) -> list[float]:
        vectors = await asyncio.to_thread(self._encode, [bge_query_text(text)])
        return vectors[0]

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prepared = [bge_passage_text(text) for text in texts]
        vectors: list[list[float]] = []
        # Small batches bound padding/activation memory (batch 32 peaked at ~1.4 GB RSS,
        # batch 8 at ~0.45 GB) and are faster on CPU; ingest passes whole documents here.
        for offset in range(0, len(prepared), ENCODE_BATCH):
            vectors.extend(
                await asyncio.to_thread(self._encode, prepared[offset : offset + ENCODE_BATCH])
            )
        return vectors

    def _encode(self, texts: list[str]) -> list[list[float]]:
        np = self._np
        encodings = self._tokenizer.encode_batch(texts)
        feeds = {
            "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
            "token_type_ids": np.array([e.type_ids for e in encodings], dtype=np.int64),
        }
        hidden = self._session.run(
            None, {name: value for name, value in feeds.items() if name in self._input_names}
        )[0]
        cls = hidden[:, 0, :]
        cls = cls / np.clip(np.linalg.norm(cls, axis=1, keepdims=True), 1e-12, None)
        return cast(list[list[float]], cls.astype(float).tolist())
