from pubtator_link.services.workflow_help import WorkflowHelpService


def test_workflow_help_includes_metadata_and_review_index_steps() -> None:
    service = WorkflowHelpService()

    response = service.get_help("clinical_genetics_review")

    names = [step.tool_name for step in response.steps]
    assert "pubtator.search_biomedical_entities" in names
    assert "pubtator.find_entity_relations" in names
    assert "pubtator.search_literature" in names
    assert "pubtator.get_publication_metadata" in names
    assert "pubtator.index_review_evidence" in names
    assert "pubtator.retrieve_review_context_batch" in names
    assert response.meta["next_commands"]


def test_workflow_help_entity_discovery_uses_discovery_tools() -> None:
    response = WorkflowHelpService().get_help("entity_discovery")

    assert response.tool_sequence == [
        "pubtator.search_biomedical_entities",
        "pubtator.find_entity_relations",
        "pubtator.lookup_mesh",
        "pubtator.search_literature",
    ]
    assert response.meta["next_commands"][0] == "pubtator.search_biomedical_entities"


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
    assert "pubtator.get_review_audit_trail" in help_text
