from __future__ import annotations

from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteraturePaper,
    ProviderWarning,
)
from pubtator_link.services.literature_graph_compact import (
    access_flags,
    access_summary,
    coalesced_provider_warnings,
    intent_flags_for_query,
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
