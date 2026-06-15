from __future__ import annotations

import json

from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteratureGraphResponseMeta,
    LiteraturePaper,
    ProviderWarning,
    PublicationCitationGraphRequest,
)
from pubtator_link.services.literature_graph_compact import (
    COMPACT_BUDGET_BYTES,
    access_flags,
    access_summary,
    coalesced_provider_warnings,
    graph_detail_next_commands,
    graph_payload_json_bytes,
    graph_request_metadata,
    intent_flags_for_query,
    mark_graph_payload_truncated,
    response_size_class,
)


def test_access_summary_priority_prefers_full_text_over_open_access() -> None:
    paper = LiteraturePaper(
        pmid="1",
        availability=LiteratureAvailability(
            has_pmc_full_text=True,
            is_open_access=True,
            has_pdf=True,
        ),
    )

    assert access_summary(paper) == "full_text"
    assert access_flags(paper) == {
        "has_pmc_full_text": True,
        "is_open_access": True,
        "has_pdf": True,
    }


def test_response_size_class_thresholds() -> None:
    assert response_size_class(4096) == "small"
    assert response_size_class(4097) == "medium"
    assert response_size_class(12288) == "medium"
    assert response_size_class(12289) == "large"


def test_coalesces_repeated_provider_warnings() -> None:
    warnings = [
        ProviderWarning(provider="unpaywall", status="provider_disabled", message="missing email"),
        ProviderWarning(provider="unpaywall", status="provider_disabled", message="missing email"),
        ProviderWarning(
            provider="crossref", status="provider_failed", message="timeout", retryable=True
        ),
    ]

    coalesced = coalesced_provider_warnings(warnings)

    assert len(coalesced) == 2
    assert coalesced[0].provider == "unpaywall"
    assert coalesced[0].message == "missing email (repeated 2 times)"
    assert coalesced[1].retryable is True


def test_intent_flags_are_normalized_and_plural_aware() -> None:
    flags = intent_flags_for_query(
        "Guidelines for Turkish children with MEFV VUS and colchicine resistance"
    )

    assert flags == {
        "guideline_intent",
        "pediatric_intent",
        "population_intent",
        "variant_intent",
        "treatment_intent",
    }


def test_graph_request_signature_metadata_is_deterministic_for_request() -> None:
    request = PublicationCitationGraphRequest(pmid="123", response_mode="compact")

    first = graph_request_metadata(
        tool_name="get_publication_citation_graph",
        request=request,
        source_versions={"pubmed": "live"},
    )
    second = graph_request_metadata(
        tool_name="get_publication_citation_graph",
        request=request,
        source_versions={"pubmed": "live"},
    )

    assert first.request_signature == second.request_signature
    assert first.request_signature is not None
    assert first.cache_key == first.request_signature
    assert first.snapshot_date is not None
    assert first.source_versions["pubmed"] == "live"


def test_graph_payload_json_bytes_uses_compact_json() -> None:
    payload = {"source": LiteraturePaper(pmid="123").model_dump(mode="json")}
    expected = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    assert graph_payload_json_bytes(payload) == len(expected)
    assert 0 < graph_payload_json_bytes(payload) < 1024


def test_graph_detail_next_commands_preserve_request_args() -> None:
    request = PublicationCitationGraphRequest(pmid="123", response_mode="compact")

    commands = graph_detail_next_commands(
        tool_name="get_publication_citation_graph",
        request=request,
        modes=("full", "nodes_edges"),
    )

    assert commands[0]["tool"] == "get_publication_citation_graph"
    assert commands[0]["arguments"]["pmid"] == "123"
    assert commands[0]["arguments"]["response_mode"] == "full"
    assert commands[1]["arguments"]["response_mode"] == "nodes_edges"


def test_mark_graph_payload_truncated_merges_counts_and_budget_advice() -> None:
    meta = LiteratureGraphResponseMeta(response_mode="compact")

    updated = mark_graph_payload_truncated(
        meta,
        omitted_counts={"candidate_details": 3},
        budget_bytes=COMPACT_BUDGET_BYTES,
    )

    assert updated.truncated is True
    assert updated.omitted_counts["candidate_details"] == 3
    assert "12000" in updated.budget_advice or "12 KiB" in updated.budget_advice
