from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pubtator_link.mcp.profiles import MCPToolProfile

ToolCategory = Literal[
    "metadata",
    "diagnostics",
    "literature",
    "discovery",
    "publication",
    "review",
    "retrieval",
    "annotation",
    "audit",
]
ToolStability = Literal["lean", "advanced", "compat", "admin"]
CatalogProfile = Literal["lean", "full", "readonly"]


@dataclass(frozen=True)
class ToolCatalogEntry:
    name: str
    title: str
    category: ToolCategory
    profiles: tuple[CatalogProfile, ...]
    stability: ToolStability
    description: str
    do_not_use_for: tuple[str, ...]
    example: str
    next_tools: tuple[str, ...]
    resource_links: tuple[str, ...]
    output_schema_name: str | None
    has_output_schema: bool


@dataclass(frozen=True)
class ToolCatalogSupplement:
    category: ToolCategory
    profiles: tuple[CatalogProfile, ...]
    stability: ToolStability
    do_not_use_for: tuple[str, ...]
    example: str
    next_tools: tuple[str, ...] = ()
    resource_links: tuple[str, ...] = ()


TOOL_CATALOG_SUPPLEMENTS: dict[str, ToolCatalogSupplement] = {
    "pubtator.add_evidence_certainty": ToolCatalogSupplement(
        category="review",
        profiles=("full",),
        stability="advanced",
        do_not_use_for=("automated certainty grading", "clinical decision support"),
        example='{"review_id":"demo","outcome":"overall survival","overall_certainty":"low"}',
        next_tools=("pubtator.list_evidence_certainty",),
        resource_links=("pubtator://reviews/{review_id}/audit",),
    ),
    "pubtator.convert_article_ids": ToolCatalogSupplement(
        category="discovery",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("article text retrieval",),
        example='{"ids":["PMC123456","10.1000/example"],"source":"auto"}',
        next_tools=("pubtator.get_publication_metadata",),
    ),
    "pubtator.diagnostics": ToolCatalogSupplement(
        category="diagnostics",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("biomedical literature search",),
        example="{}",
        next_tools=("pubtator.get_server_capabilities",),
    ),
    "pubtator.estimate_publication_context": ToolCatalogSupplement(
        category="publication",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("returning passage text",),
        example='{"pmids":["12345"],"max_passages_per_pmid":6}',
        next_tools=("pubtator.get_publication_passages",),
    ),
    "pubtator.export_review_audit_bundle": ToolCatalogSupplement(
        category="audit",
        profiles=("full",),
        stability="compat",
        do_not_use_for=("routine context retrieval",),
        example='{"review_id":"demo","fallback_inline":true}',
        next_tools=("pubtator.get_review_audit_trail",),
        resource_links=("pubtator://reviews/{review_id}/audit",),
    ),
    "pubtator.fetch_pmc_annotations": ToolCatalogSupplement(
        category="annotation",
        profiles=("full",),
        stability="advanced",
        do_not_use_for=("compact grounded answers",),
        example='{"pmcids":["PMC123456"],"format":"biocjson"}',
        next_tools=("pubtator.get_publication_passages",),
    ),
    "pubtator.fetch_publication_annotations": ToolCatalogSupplement(
        category="annotation",
        profiles=("full",),
        stability="advanced",
        do_not_use_for=("compact grounded answers",),
        example='{"pmids":["12345"],"format":"biocjson","full":false}',
        next_tools=("pubtator.get_publication_passages",),
    ),
    "pubtator.find_entity_relations": ToolCatalogSupplement(
        category="discovery",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("canonical entity lookup",),
        example='{"entity_id":"@CHEMICAL_remdesivir"}',
        next_tools=("pubtator.search_literature",),
    ),
    "pubtator.find_related_articles": ToolCatalogSupplement(
        category="discovery",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("initial topic search without seed PMIDs",),
        example='{"pmids":["12345"],"mode":"similar","limit":20}',
        next_tools=("pubtator.preflight_review_sources",),
    ),
    "pubtator.get_evidence_certainty": ToolCatalogSupplement(
        category="review",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("listing all judgments",),
        example='{"review_id":"demo","certainty_id":"certainty-1"}',
        next_tools=("pubtator.list_evidence_certainty",),
    ),
    "pubtator.get_neighboring_review_passages": ToolCatalogSupplement(
        category="retrieval",
        profiles=("full", "readonly"),
        stability="compat",
        do_not_use_for=("new semantic retrieval",),
        example='{"review_id":"demo","passage_id":"p1","before":1,"after":1}',
        next_tools=("pubtator.retrieve_review_context_batch",),
        resource_links=("pubtator://reviews/{review_id}/passages/{passage_id}",),
    ),
    "pubtator.get_publication_metadata": ToolCatalogSupplement(
        category="publication",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("article passage text",),
        example='{"pmids":["12345"],"include_citations":"nlm"}',
        next_tools=("pubtator.get_publication_passages",),
    ),
    "pubtator.get_publication_passages": ToolCatalogSupplement(
        category="publication",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("prepared review RAG retrieval",),
        example='{"pmids":["12345"],"max_passages_per_pmid":6,"verbosity":"standard"}',
        next_tools=("pubtator.preflight_review_sources",),
    ),
    "pubtator.get_research_session_status": ToolCatalogSupplement(
        category="review",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("creating or modifying sessions",),
        example='{"review_id":"demo","session_id":"session-1"}',
        next_tools=("pubtator.index_review_evidence",),
        resource_links=("pubtator://reviews/{review_id}/sessions/{session_id}",),
    ),
    "pubtator.get_review_audit_trail": ToolCatalogSupplement(
        category="audit",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("retrieving full passage context",),
        example='{"review_id":"demo","passage_ids":["p1"],"max_chars_per_passage":500}',
        resource_links=("pubtator://reviews/{review_id}/audit/{passage_id}",),
    ),
    "pubtator.get_review_index_summary": ToolCatalogSupplement(
        category="review",
        profiles=("full", "readonly"),
        stability="admin",
        do_not_use_for=("loading passage samples",),
        example='{"review_id":"demo"}',
        next_tools=("pubtator.inspect_review_index",),
        resource_links=("pubtator://reviews/{review_id}",),
    ),
    "pubtator.get_review_passages_by_id": ToolCatalogSupplement(
        category="retrieval",
        profiles=("full", "readonly"),
        stability="compat",
        do_not_use_for=("searching unknown relevant passages",),
        example='{"review_id":"demo","passage_ids":["p1"]}',
        next_tools=("pubtator.get_review_audit_trail",),
        resource_links=("pubtator://reviews/{review_id}/passages/{passage_id}",),
    ),
    "pubtator.get_server_capabilities": ToolCatalogSupplement(
        category="metadata",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("task-specific workflow steps",),
        example='{"details":["tools","workflow_help"]}',
        next_tools=("pubtator.workflow_help",),
        resource_links=("pubtator://capabilities",),
    ),
    "pubtator.get_text_annotation_results": ToolCatalogSupplement(
        category="annotation",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("submitting new text",),
        example='{"session_id":"session-12345678"}',
        next_tools=("pubtator.search_biomedical_entities",),
    ),
    "pubtator.index_review_evidence": ToolCatalogSupplement(
        category="review",
        profiles=("lean", "full"),
        stability="lean",
        do_not_use_for=("ad hoc passage retrieval without a review_id",),
        example='{"review_id":"demo","pmids":["12345"],"wait_until_ready":true}',
        next_tools=("pubtator.inspect_review_index", "pubtator.retrieve_review_context_batch"),
        resource_links=("pubtator://reviews/{review_id}",),
    ),
    "pubtator.inspect_review_index": ToolCatalogSupplement(
        category="review",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("retrieving final answer context",),
        example='{"review_id":"demo","include_passage_samples":true}',
        next_tools=("pubtator.retrieve_review_context_batch",),
        resource_links=("pubtator://reviews/{review_id}",),
    ),
    "pubtator.list_evidence_certainty": ToolCatalogSupplement(
        category="review",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("creating certainty judgments",),
        example='{"review_id":"demo"}',
        next_tools=("pubtator.get_evidence_certainty",),
    ),
    "pubtator.list_research_sessions": ToolCatalogSupplement(
        category="review",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("inspecting a specific session in detail",),
        example='{"review_id":"demo"}',
        next_tools=("pubtator.get_research_session_status",),
        resource_links=("pubtator://reviews/{review_id}/sessions",),
    ),
    "pubtator.list_review_indexes": ToolCatalogSupplement(
        category="review",
        profiles=("full", "readonly"),
        stability="admin",
        do_not_use_for=("retrieving review passages",),
        example='{"limit":20,"offset":0}',
        next_tools=("pubtator.get_review_index_summary",),
    ),
    "pubtator.lookup_citation": ToolCatalogSupplement(
        category="discovery",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("citation formatting",),
        example='{"citations":["Smith J. Example disease study. 2024."]}',
        next_tools=("pubtator.get_publication_metadata",),
    ),
    "pubtator.lookup_mesh": ToolCatalogSupplement(
        category="discovery",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("article retrieval",),
        example='{"query":"breast cancer","limit":10}',
        next_tools=("pubtator.search_literature",),
    ),
    "pubtator.lookup_variant_evidence": ToolCatalogSupplement(
        category="literature",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("clinical classification",),
        example='{"gene":"BRCA1","variant":"c.68_69delAG"}',
        next_tools=("pubtator.search_literature",),
    ),
    "pubtator.preflight_review_sources": ToolCatalogSupplement(
        category="review",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("indexing or retrieving passages",),
        example='{"pmids":["12345","67890"]}',
        next_tools=("pubtator.index_review_evidence",),
    ),
    "pubtator.record_review_context": ToolCatalogSupplement(
        category="audit",
        profiles=("lean", "full"),
        stability="lean",
        do_not_use_for=("retrieving passages",),
        example='{"review_id":"demo","passage_ids":["p1"],"note":"used in answer"}',
        next_tools=("pubtator.get_review_audit_trail",),
        resource_links=("pubtator://reviews/{review_id}/audit",),
    ),
    "pubtator.retrieve_review_context": ToolCatalogSupplement(
        category="retrieval",
        profiles=("full", "readonly"),
        stability="compat",
        do_not_use_for=("multiple query variants in one call",),
        example='{"review_id":"demo","question":"EGFR resistance","max_passages":8}',
        next_tools=("pubtator.get_review_audit_trail",),
    ),
    "pubtator.retrieve_review_context_batch": ToolCatalogSupplement(
        category="retrieval",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("unindexed PubMed-only article fetching",),
        example='{"review_id":"demo","queries":["EGFR resistance","osimertinib resistance"]}',
        next_tools=("pubtator.record_review_context", "pubtator.get_review_audit_trail"),
        resource_links=("pubtator://reviews/{review_id}/llm-context",),
    ),
    "pubtator.review_quickstart": ToolCatalogSupplement(
        category="review",
        profiles=("full",),
        stability="advanced",
        do_not_use_for=("readonly deployments",),
        example='{"topic":"EGFR resistance in lung cancer","n_pmids":8}',
        next_tools=("pubtator.retrieve_review_context_batch",),
    ),
    "pubtator.search_biomedical_entities": ToolCatalogSupplement(
        category="discovery",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("literature search by article topic",),
        example='{"query":"TP53","concept":"Gene","limit":10}',
        next_tools=("pubtator.search_literature",),
        resource_links=("pubtator://bioconcepts",),
    ),
    "pubtator.search_guidelines": ToolCatalogSupplement(
        category="literature",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("non-guideline exhaustive PubMed search",),
        example='{"text":"asthma treatment adults","limit":5}',
        next_tools=("pubtator.preflight_review_sources",),
    ),
    "pubtator.search_literature": ToolCatalogSupplement(
        category="literature",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("fetching known PMID passage text",),
        example='{"text":"BRCA1 ovarian cancer PARP inhibitor","limit":5,"metadata":"basic"}',
        next_tools=("pubtator.preflight_review_sources",),
    ),
    "pubtator.stage_research_session": ToolCatalogSupplement(
        category="review",
        profiles=("full",),
        stability="advanced",
        do_not_use_for=("readonly deployments",),
        example='{"review_id":"demo","query":"BRCA1 PARP inhibitor","max_candidates":20}',
        next_tools=("pubtator.get_research_session_status", "pubtator.index_review_evidence"),
        resource_links=("pubtator://reviews/{review_id}/sessions/{session_id}",),
    ),
    "pubtator.submit_text_annotation": ToolCatalogSupplement(
        category="annotation",
        profiles=("full",),
        stability="advanced",
        do_not_use_for=("PubMed or PMC ID annotation export",),
        example='{"text":"BRCA1 is associated with breast cancer.","bioconcepts":"Gene,Disease"}',
        next_tools=("pubtator.get_text_annotation_results",),
        resource_links=("pubtator://text-processing",),
    ),
    "pubtator.suggest_corpus": ToolCatalogSupplement(
        category="discovery",
        profiles=("full", "readonly"),
        stability="advanced",
        do_not_use_for=("final evidence retrieval",),
        example='{"question":"EGFR resistance in lung cancer","max_pmids":8}',
        next_tools=("pubtator.preflight_review_sources", "pubtator.index_review_evidence"),
    ),
    "pubtator.workflow_help": ToolCatalogSupplement(
        category="metadata",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("server capability inventory",),
        example='{"task":"clinical_genetics_review"}',
        next_tools=("pubtator.search_literature",),
        resource_links=("pubtator://workflow-help",),
    ),
}


def _tool_output_schema(tool: object) -> dict[str, Any] | None:
    schema = getattr(tool, "output_schema", None) or getattr(tool, "outputSchema", None)
    if schema is None:
        metadata = getattr(tool, "fn_metadata", None)
        schema = getattr(metadata, "output_schema", None) if metadata is not None else None
    return schema if isinstance(schema, dict) else None


def build_tool_catalog(
    mcp: Any,
    *,
    profile: MCPToolProfile,
) -> dict[str, ToolCatalogEntry]:
    tools = mcp._tool_manager._tools
    registered_tool_names = set(tools)
    catalog: dict[str, ToolCatalogEntry] = {}
    for name, tool in sorted(tools.items()):
        supplement = TOOL_CATALOG_SUPPLEMENTS[name]
        if profile not in supplement.profiles:
            raise ValueError(f"{name} is registered but not cataloged for profile {profile!r}")
        output_schema = _tool_output_schema(tool)
        output_schema_name = output_schema.get("title") if output_schema is not None else None
        catalog[name] = ToolCatalogEntry(
            name=getattr(tool, "name", name),
            title=getattr(tool, "title", name),
            category=supplement.category,
            profiles=supplement.profiles,
            stability=supplement.stability,
            description=getattr(tool, "description", "") or "",
            do_not_use_for=supplement.do_not_use_for,
            example=supplement.example,
            next_tools=tuple(
                tool for tool in supplement.next_tools if tool in registered_tool_names
            ),
            resource_links=supplement.resource_links,
            output_schema_name=output_schema_name if isinstance(output_schema_name, str) else None,
            has_output_schema=output_schema is not None,
        )
    return catalog
