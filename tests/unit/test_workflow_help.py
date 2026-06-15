from pubtator_link.services.workflow_help import WorkflowHelpService


def test_workflow_help_includes_metadata_and_review_index_steps() -> None:
    service = WorkflowHelpService()

    response = service.get_help("clinical_genetics_review")

    names = [step.tool_name for step in response.steps]
    assert "ground_question" in names
    assert "search_biomedical_entities" in names
    assert "find_entity_relations" in names
    assert "search_literature" in names
    assert "get_publication_metadata" in names
    assert "index_review_evidence" in names
    assert "get_review_context_batch" in names
    assert response.meta["next_commands"]


def test_workflow_help_entity_discovery_uses_discovery_tools() -> None:
    response = WorkflowHelpService().get_help("entity_discovery")

    assert response.tool_sequence == [
        "search_biomedical_entities",
        "find_entity_relations",
        "get_mesh",
        "search_literature",
    ]
    assert response.meta["next_commands"][0] == "search_biomedical_entities"


def test_workflow_help_does_not_show_prepare_mode_argument() -> None:
    help_text = (
        WorkflowHelpService().get_help("clinical_genetics_review").model_dump_json(by_alias=True)
    )

    assert "prepare_mode" not in help_text


def test_workflow_help_mentions_recovery_quote_confidence_and_audit_trail() -> None:
    help_text = (
        WorkflowHelpService().get_help("clinical_genetics_review").model_dump_json(by_alias=True)
    )

    assert "recovery" in help_text
    assert "quote" in help_text
    assert "confidence_for_grounding" in help_text
    assert "get_review_audit_trail" in help_text


def test_workflow_help_mentions_genereviews_nbk_recovery() -> None:
    payload = WorkflowHelpService().get_help("clinical_genetics_review").model_dump_json()

    assert "GeneReviews" in payload
    assert "NBK" in payload
    assert "get_citation" in payload


def test_workflow_help_documents_guideline_search_as_filtered_literature_search() -> None:
    payload = WorkflowHelpService().get_help("clinical_genetics_review").model_dump_json()

    assert "search_guidelines" in payload
    assert "filtered search_literature" in payload


def test_workflow_help_mentions_literature_graph_bundle_boundary() -> None:
    payload = WorkflowHelpService().get_help("graph").model_dump()
    text = str(payload)

    assert "build_topic_literature_map" in text
    assert "get_publication_citation_graph" in text
    assert "find_related_evidence_candidates" in text
    assert "ToolSearch" in text


def test_workflow_help_routes_hyphenated_literature_graph_aliases() -> None:
    for task in ("topic-map", "topic map", "literature-map", "literature map", "citation graph"):
        response = WorkflowHelpService().get_help(task)

        assert response.task == "graph"
        assert "build_topic_literature_map" in response.tool_sequence
        assert "get_publication_citation_graph" in response.tool_sequence


def test_workflow_help_keeps_citation_audit_aliases_on_audit_workflow() -> None:
    for task in (
        "citation_audit",
        "citation audit",
        "citation-audit",
        "citation audit workflow",
    ):
        response = WorkflowHelpService().get_help(task)

        assert response.task == "citation_audit"
        assert response.tool_sequence[0] == "get_citation"
        assert "get_publication_citation_graph" not in response.tool_sequence
