from __future__ import annotations

from pubtator_link.services.review_context.embeddings import (
    FakeEmbeddingProvider,
    bge_passage_text,
    bge_query_text,
    text_hash,
)


def test_text_hash_is_stable_and_distinguishes_text() -> None:
    assert text_hash("same text") == text_hash("same text")
    assert text_hash("same text") != text_hash("another text")


async def test_fake_embedding_provider_embeds_passages_with_configured_dimension() -> None:
    provider = FakeEmbeddingProvider(dim=384)

    vectors = await provider.embed_passages(["alpha", "beta"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 384


def test_bge_text_helpers_apply_expected_query_prefix_only() -> None:
    assert bge_query_text("dose escalation").startswith(
        "Represent this sentence for searching relevant passages: "
    )
    assert bge_passage_text("dose escalation") == "dose escalation"
