from __future__ import annotations

import json

from pubtator_link.repositories.review_rerag_mappers import (
    _infer_source_coverage,
    _parse_execute_count,
    _passage_from_row,
    _preparation_status_from_row,
    _recall_tsquery,
)


def test_preparation_status_from_missing_row_defaults_to_zero() -> None:
    status = _preparation_status_from_row(None)

    assert status.total == 0
    assert status.failed == 0


def test_passage_from_row_decodes_json_metadata() -> None:
    row = {
        "passage_id": "p1",
        "review_id": "r1",
        "source_id": "s1",
        "source_kind": "pubtator_abstract",
        "pmid": "123",
        "pmcid": None,
        "doi": None,
        "url": None,
        "section": "abstract",
        "heading_path": "Abstract",
        "page": None,
        "text": "MEFV colchicine evidence",
        "entity_ids": ["@GENE_MEFV"],
        "relation_types": [],
        "screening_status": "included",
        "source_metadata": json.dumps({"journal": "Example"}),
        "lexical_rank": 2.5,
    }

    passage = _passage_from_row(row)

    assert passage.passage_id == "p1"
    assert passage.source_metadata == {"journal": "Example"}
    assert passage.lexical_rank == 2.5


def test_infer_source_coverage_prefers_full_text_sections() -> None:
    assert (
        _infer_source_coverage(
            source_kind="pubtator_full_bioc",
            sections=["abstract", "results"],
            attempt_statuses=[],
        )
        == "full_text"
    )
    assert (
        _infer_source_coverage(
            source_kind="pubtator_abstract",
            sections=["abstract"],
            attempt_statuses=[],
        )
        == "abstract_only"
    )


def test_parse_execute_count_and_recall_query_are_stable() -> None:
    assert _parse_execute_count("INSERT 0 7") == 7
    assert _parse_execute_count("UPDATE") == 0
    assert _recall_tsquery("MEFV MEFV colchicine response in FMF") == (
        "mefv | colchicine | response | fmf"
    )
