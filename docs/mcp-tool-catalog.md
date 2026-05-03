# MCP Tool Catalog

Generated from the runtime FastMCP tool registry plus catalog-only supplements.
Do not edit by hand; run `uv run python scripts/generate_mcp_tool_catalog.py`.

## `pubtator.add_evidence_certainty`

- Name: `pubtator.add_evidence_certainty`
- Title: Add Evidence Certainty
- Category: `review`
- Profiles: `full`
- Stability: `advanced`
- Description: Use this when a user needs to store a user-supplied GRADE-style evidence certainty judgment linked to prepared passage IDs. The backend stores the judgment; it does not compute certainty.
- Do not use for: `automated certainty grading`, `clinical decision support`
- Example: `{"review_id":"demo","outcome":"overall survival","overall_certainty":"low"}`
- Next tools by profile: full: `pubtator.list_evidence_certainty`
- Resource links: `pubtator://reviews/{review_id}/audit`
- Output schema: `EvidenceCertaintyResponse`; has_output_schema: `yes`

## `pubtator.convert_article_ids`

- Name: `pubtator.convert_article_ids`
- Title: Convert Article IDs
- Category: `discovery`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user provides article identifiers such as PMIDs, PMCIDs, or DOIs and needs normalized candidate PMIDs for research workflows.
- Do not use for: `article text retrieval`
- Example: `{"ids":["PMC123456","10.1000/example"],"source":"auto"}`
- Next tools by profile: full: `pubtator.get_publication_metadata`; readonly: `pubtator.get_publication_metadata`
- Resource links: None
- Output schema: `ArticleIdConversionResponse`; has_output_schema: `yes`

## `pubtator.diagnostics`

- Name: `pubtator.diagnostics`
- Title: PubTator-Link Diagnostics
- Category: `diagnostics`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a client needs PubTator-Link subsystem status and recovery commands.
- Do not use for: `biomedical literature search`
- Example: `{}`
- Next tools by profile: lean: `pubtator.get_server_capabilities`; full: `pubtator.get_server_capabilities`; readonly: `pubtator.get_server_capabilities`
- Resource links: None
- Output schema: `DiagnosticsResponse`; has_output_schema: `yes`

## `pubtator.estimate_publication_context`

- Name: `pubtator.estimate_publication_context`
- Title: Estimate Publication Context
- Category: `publication`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user needs to estimate passage count and context size before fetching publication passages. Do not use this for text retrieval; use pubtator.get_publication_passages. Next: pubtator.get_publication_passages.
- Do not use for: `returning passage text`
- Example: `{"pmids":["12345"],"max_passages_per_pmid":6}`
- Next tools by profile: full: `pubtator.get_publication_passages`; readonly: `pubtator.get_publication_passages`
- Resource links: None
- Output schema: `PublicationContextEstimateResponse`; has_output_schema: `yes`

## `pubtator.export_review_audit_bundle`

- Name: `pubtator.export_review_audit_bundle`
- Title: Export Review Audit Bundle
- Category: `audit`
- Profiles: `full`
- Stability: `compat`
- Description: Use this when a user needs to export review preparation status, source coverage, resolver attempts, retrieval runs, passage IDs, and stable citation keys for scientific auditability.
- Do not use for: `routine context retrieval`
- Example: `{"review_id":"demo","fallback_inline":true}`
- Next tools by profile: full: `pubtator.get_review_audit_trail`
- Resource links: `pubtator://reviews/{review_id}/audit`
- Output schema: `McpReviewAuditBundleResponse`; has_output_schema: `yes`

## `pubtator.fetch_pmc_annotations`

- Name: `pubtator.fetch_pmc_annotations`
- Title: Fetch PMC Annotations
- Category: `annotation`
- Profiles: `full`
- Stability: `advanced`
- Description: Use this when a user provides PMC IDs and needs raw PubTator full-text BioC annotation export. Do not use this for compact grounded answers; use pubtator.get_publication_passages. Next: pubtator.get_publication_passages.
- Do not use for: `compact grounded answers`
- Example: `{"pmcids":["PMC123456"],"format":"biocjson"}`
- Next tools by profile: full: `pubtator.get_publication_passages`
- Resource links: None
- Output schema: `PublicationExportResponse`; has_output_schema: `yes`

## `pubtator.fetch_publication_annotations`

- Name: `pubtator.fetch_publication_annotations`
- Title: Fetch Publication Annotations
- Category: `annotation`
- Profiles: `full`
- Stability: `advanced`
- Description: Use this when a user provides PubMed IDs and needs raw PubTator BioC annotation export. Do not use this for compact grounded answers; use pubtator.get_publication_passages. Next: pubtator.get_publication_passages.
- Do not use for: `compact grounded answers`
- Example: `{"pmids":["12345"],"format":"biocjson","full":false}`
- Next tools by profile: full: `pubtator.get_publication_passages`
- Resource links: None
- Output schema: `PublicationExportResponse`; has_output_schema: `yes`

## `pubtator.find_entity_relations`

- Name: `pubtator.find_entity_relations`
- Title: Find Entity Relations
- Category: `discovery`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user has a PubTator entity ID and needs literature-derived related entities to expand a corpus. Do not use this for canonical entity lookup; use pubtator.search_biomedical_entities. Next: pubtator.search_literature.
- Do not use for: `canonical entity lookup`
- Example: `{"entity_id":"@CHEMICAL_remdesivir"}`
- Next tools by profile: full: `pubtator.search_literature`; readonly: `pubtator.search_literature`
- Resource links: None
- Output schema: `RelationsResponse`; has_output_schema: `yes`

## `pubtator.find_related_articles`

- Name: `pubtator.find_related_articles`
- Title: Find Related Articles
- Category: `discovery`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user has seed PMIDs and needs similar, cited-by, or reference-linked articles to expand a research corpus.
- Do not use for: `initial topic search without seed PMIDs`
- Example: `{"pmids":["12345"],"mode":"similar","limit":20}`
- Next tools by profile: full: `pubtator.preflight_review_sources`; readonly: `pubtator.preflight_review_sources`
- Resource links: None
- Output schema: `RelatedArticlesResponse`; has_output_schema: `yes`

## `pubtator.get_evidence_certainty`

- Name: `pubtator.get_evidence_certainty`
- Title: Get Evidence Certainty
- Category: `review`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user needs one user-supplied evidence certainty judgment.
- Do not use for: `listing all judgments`
- Example: `{"review_id":"demo","certainty_id":"certainty-1"}`
- Next tools by profile: full: `pubtator.list_evidence_certainty`; readonly: `pubtator.list_evidence_certainty`
- Resource links: None
- Output schema: `EvidenceCertaintyResponse`; has_output_schema: `yes`

## `pubtator.get_neighboring_review_passages`

- Name: `pubtator.get_neighboring_review_passages`
- Title: Get Neighboring Review Passages
- Category: `retrieval`
- Profiles: `full`, `readonly`
- Stability: `compat`
- Description: Use this when a user needs prepared review passages near a cited stable passage ID for local context expansion. This only reads the review index and does not call upstream APIs.
- Do not use for: `new semantic retrieval`
- Example: `{"review_id":"demo","passage_id":"p1","before":1,"after":1}`
- Next tools by profile: full: `pubtator.retrieve_review_context_batch`; readonly: `pubtator.retrieve_review_context_batch`
- Resource links: `pubtator://reviews/{review_id}/passages/{passage_id}`
- Output schema: `ReviewPassageLookupResponse`; has_output_schema: `yes`

## `pubtator.get_publication_metadata`

- Name: `pubtator.get_publication_metadata`
- Title: Get Publication Metadata
- Category: `publication`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user needs citation-grade metadata for known PMIDs. Do not use this for article text or annotations; use pubtator.get_publication_passages. Next: pubtator.get_publication_passages.
- Do not use for: `article passage text`
- Example: `{"pmids":["12345"],"include_citations":"nlm"}`
- Next tools by profile: lean: `pubtator.get_publication_passages`; full: `pubtator.get_publication_passages`; readonly: `pubtator.get_publication_passages`
- Resource links: None
- Output schema: `PublicationMetadataResponse`; has_output_schema: `yes`

## `pubtator.get_publication_passages`

- Name: `pubtator.get_publication_passages`
- Title: Get Publication Passages
- Category: `publication`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user needs compact citable publication passages from PMIDs without raw BioC. Do not use this for prepared review RAG; use pubtator.retrieve_review_context_batch. Next: pubtator.retrieve_review_context_batch.
- Do not use for: `prepared review RAG retrieval`
- Example: `{"pmids":["12345"],"max_passages_per_pmid":6,"verbosity":"standard"}`
- Next tools by profile: lean: `pubtator.preflight_review_sources`; full: `pubtator.preflight_review_sources`; readonly: `pubtator.preflight_review_sources`
- Resource links: None
- Output schema: `PublicationPassageResponse`; has_output_schema: `yes`

## `pubtator.get_research_session_status`

- Name: `pubtator.get_research_session_status`
- Title: Get Research Session Status
- Category: `review`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user needs staged candidate, coverage, and preparation status for a research session.
- Do not use for: `creating or modifying sessions`
- Example: `{"review_id":"demo","session_id":"session-1"}`
- Next tools by profile: full: `pubtator.index_review_evidence`; readonly: None
- Resource links: `pubtator://reviews/{review_id}/sessions/{session_id}`
- Output schema: `ResearchSessionStatusResponse`; has_output_schema: `yes`

## `pubtator.get_review_audit_trail`

- Name: `pubtator.get_review_audit_trail`
- Title: Get Review Audit Trail
- Category: `audit`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user needs a copy-ready audit block for selected prepared review passage IDs without calling upstream APIs.
- Do not use for: `retrieving full passage context`
- Example: `{"review_id":"demo","passage_ids":["p1"],"max_chars_per_passage":500}`
- Next tools by profile: lean: None; full: None; readonly: None
- Resource links: `pubtator://reviews/{review_id}/audit/{passage_id}`
- Output schema: `ReviewAuditTrailResponse`; has_output_schema: `yes`

## `pubtator.get_review_index_summary`

- Name: `pubtator.get_review_index_summary`
- Title: Get Review Index Summary
- Category: `review`
- Profiles: `full`, `readonly`
- Stability: `admin`
- Description: Use this when a user needs one persisted review index summary without loading passage samples.
- Do not use for: `loading passage samples`
- Example: `{"review_id":"demo"}`
- Next tools by profile: full: `pubtator.inspect_review_index`; readonly: `pubtator.inspect_review_index`
- Resource links: `pubtator://reviews/{review_id}`
- Output schema: `ReviewIndexSummaryResponse`; has_output_schema: `yes`

## `pubtator.get_review_passages_by_id`

- Name: `pubtator.get_review_passages_by_id`
- Title: Get Review Passages By ID
- Category: `retrieval`
- Profiles: `full`, `readonly`
- Stability: `compat`
- Description: Use this when a user needs exact prepared review passages by stable passage IDs from prior context packs or audit bundles. This only reads the review index and does not call upstream APIs.
- Do not use for: `searching unknown relevant passages`
- Example: `{"review_id":"demo","passage_ids":["p1"]}`
- Next tools by profile: full: `pubtator.get_review_audit_trail`; readonly: `pubtator.get_review_audit_trail`
- Resource links: `pubtator://reviews/{review_id}/passages/{passage_id}`
- Output schema: `ReviewPassageLookupResponse`; has_output_schema: `yes`

## `pubtator.get_server_capabilities`

- Name: `pubtator.get_server_capabilities`
- Title: Get PubTator-Link Capabilities
- Category: `metadata`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a client needs supported tools, transports, formats, and limitations. Do not use this for task-specific workflow guidance; use pubtator.workflow_help. Next: pubtator.workflow_help.
- Do not use for: `task-specific workflow steps`
- Example: `{"details":["tools","workflow_help"]}`
- Next tools by profile: lean: `pubtator.workflow_help`; full: `pubtator.workflow_help`; readonly: `pubtator.workflow_help`
- Resource links: `pubtator://capabilities`
- Output schema: `ServerCapabilitiesResponse`; has_output_schema: `yes`

## `pubtator.get_text_annotation_results`

- Name: `pubtator.get_text_annotation_results`
- Title: Get Text Annotation Results
- Category: `annotation`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user has a PubTator text annotation session ID and needs its results. Do not use this for entity lookup from names; use pubtator.search_biomedical_entities. Next: pubtator.search_biomedical_entities.
- Do not use for: `submitting new text`
- Example: `{"session_id":"session-12345678"}`
- Next tools by profile: full: `pubtator.search_biomedical_entities`; readonly: `pubtator.search_biomedical_entities`
- Resource links: None
- Output schema: `TextAnnotationResultResponse`; has_output_schema: `yes`

## `pubtator.index_review_evidence`

- Name: `pubtator.index_review_evidence`
- Title: Index Review Evidence
- Category: `review`
- Profiles: `lean`, `full`
- Stability: `lean`
- Description: Use this when a review needs review-scoped evidence preparation for a review_id and PMIDs/curated URLs. Call this before retrieve_review_context_batch, use session_id to scope staged research sessions, set wait_until_ready for small corpora, and inspect preparation_status before retrieval.
- Do not use for: `ad hoc passage retrieval without a review_id`
- Example: `{"review_id":"demo","pmids":["12345"],"wait_until_ready":true}`
- Next tools by profile: lean: `pubtator.inspect_review_index`, `pubtator.retrieve_review_context_batch`; full: `pubtator.inspect_review_index`, `pubtator.retrieve_review_context_batch`
- Resource links: `pubtator://reviews/{review_id}`
- Output schema: `IndexReviewEvidenceResponse`; has_output_schema: `yes`

## `pubtator.inspect_review_index`

- Name: `pubtator.inspect_review_index`
- Title: Inspect Review Index
- Category: `review`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user needs to inspect indexed PMIDs, sections, passage counts, and failures for a review_id, including source coverage.
- Do not use for: `retrieving final answer context`
- Example: `{"review_id":"demo","include_passage_samples":true}`
- Next tools by profile: lean: `pubtator.retrieve_review_context_batch`; full: `pubtator.retrieve_review_context_batch`; readonly: `pubtator.retrieve_review_context_batch`
- Resource links: `pubtator://reviews/{review_id}`
- Output schema: `InspectReviewIndexResponse`; has_output_schema: `yes`

## `pubtator.list_evidence_certainty`

- Name: `pubtator.list_evidence_certainty`
- Title: List Evidence Certainty
- Category: `review`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user needs user-supplied evidence certainty judgments for a review.
- Do not use for: `creating certainty judgments`
- Example: `{"review_id":"demo"}`
- Next tools by profile: full: `pubtator.get_evidence_certainty`; readonly: `pubtator.get_evidence_certainty`
- Resource links: None
- Output schema: `ListEvidenceCertaintyResponse`; has_output_schema: `yes`

## `pubtator.list_research_sessions`

- Name: `pubtator.list_research_sessions`
- Title: List Research Sessions
- Category: `review`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user needs staged research sessions for one review ID.
- Do not use for: `inspecting a specific session in detail`
- Example: `{"review_id":"demo"}`
- Next tools by profile: full: `pubtator.get_research_session_status`; readonly: `pubtator.get_research_session_status`
- Resource links: `pubtator://reviews/{review_id}/sessions`
- Output schema: `ListResearchSessionsResponse`; has_output_schema: `yes`

## `pubtator.list_review_indexes`

- Name: `pubtator.list_review_indexes`
- Title: List Review Indexes
- Category: `review`
- Profiles: `full`, `readonly`
- Stability: `admin`
- Description: Use this when a user needs persisted review indexes with preparation status, source counts, passage counts, and approximate storage size.
- Do not use for: `retrieving review passages`
- Example: `{"limit":20,"offset":0}`
- Next tools by profile: full: `pubtator.get_review_index_summary`; readonly: `pubtator.get_review_index_summary`
- Resource links: None
- Output schema: `ListReviewIndexesResponse`; has_output_schema: `yes`

## `pubtator.lookup_citation`

- Name: `pubtator.lookup_citation`
- Title: Lookup Citation
- Category: `discovery`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user provides free-text citations and needs candidate PMIDs for research evidence gathering.
- Do not use for: `citation formatting`
- Example: `{"citations":["Smith J. Example disease study. 2024."]}`
- Next tools by profile: full: `pubtator.get_publication_metadata`; readonly: `pubtator.get_publication_metadata`
- Resource links: None
- Output schema: `CitationLookupResponse`; has_output_schema: `yes`

## `pubtator.lookup_mesh`

- Name: `pubtator.lookup_mesh`
- Title: Lookup MeSH
- Category: `discovery`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user needs MeSH descriptors and candidate PubMed search terms for a biomedical research query.
- Do not use for: `article retrieval`
- Example: `{"query":"breast cancer","limit":10}`
- Next tools by profile: full: `pubtator.search_literature`; readonly: `pubtator.search_literature`
- Resource links: None
- Output schema: `MeshLookupResponse`; has_output_schema: `yes`

## `pubtator.lookup_variant_evidence`

- Name: `pubtator.lookup_variant_evidence`
- Title: Lookup Variant Evidence
- Category: `literature`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user needs source-attributed variant records and literature evidence for a gene and variant. Does not compute clinical classification.
- Do not use for: `clinical classification`
- Example: `{"gene":"BRCA1","variant":"c.68_69delAG"}`
- Next tools by profile: lean: `pubtator.search_literature`; full: `pubtator.search_literature`; readonly: `pubtator.search_literature`
- Resource links: None
- Output schema: `VariantEvidenceResponse`; has_output_schema: `yes`

## `pubtator.preflight_review_sources`

- Name: `pubtator.preflight_review_sources`
- Title: Preflight Review Sources
- Category: `review`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user needs PMID source coverage, PMC fallback availability, and likely full-text versus abstract-only retrieval before indexing review evidence.
- Do not use for: `indexing or retrieving passages`
- Example: `{"pmids":["12345","67890"]}`
- Next tools by profile: lean: `pubtator.index_review_evidence`; full: `pubtator.index_review_evidence`; readonly: None
- Resource links: None
- Output schema: `PreflightReviewSourcesResponse`; has_output_schema: `yes`

## `pubtator.record_review_context`

- Name: `pubtator.record_review_context`
- Title: Record Review Context
- Category: `audit`
- Profiles: `lean`, `full`
- Stability: `lean`
- Description: Use this when a user needs to persist compact LLM review context, selected evidence IDs, decisions, or next-step state without storing article text.
- Do not use for: `retrieving passages`
- Example: `{"review_id":"demo","event_type":"passage_selected","passage_ids":["p1"],"selected_passage_ids":["p1"],"summary":"used in answer"}`
- Next tools by profile: lean: `pubtator.get_review_audit_trail`; full: `pubtator.get_review_audit_trail`
- Resource links: `pubtator://reviews/{review_id}/llm-context/latest`
- Output schema: `RecordReviewContextResponse`; has_output_schema: `yes`

## `pubtator.retrieve_review_context`

- Name: `pubtator.retrieve_review_context`
- Title: Retrieve Review Context
- Category: `retrieval`
- Profiles: `full`, `readonly`
- Stability: `compat`
- Description: Use this when a review needs compact citable context from prepared review passages instead of raw BioC export. Use a short keyword query, PMID filters for paper-specific evidence, and diagnostics for zero-result debugging. If zero passages are returned, simplify the query, inspect the review index, or fall back to fetch_publication_annotations.
- Do not use for: `multiple query variants in one call`
- Example: `{"review_id":"demo","question":"EGFR resistance","max_passages":8}`
- Next tools by profile: full: `pubtator.get_review_audit_trail`; readonly: `pubtator.get_review_audit_trail`
- Resource links: None
- Output schema: `RetrieveReviewContextResponse`; has_output_schema: `yes`

## `pubtator.retrieve_review_context_batch`

- Name: `pubtator.retrieve_review_context_batch`
- Title: Retrieve Review Context Batch
- Category: `retrieval`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user wants multiple short review retrieval query variants in one call. Default compact mode uses query_fair budgeting, merged passages, per-query summaries, and next_steps for zero-result queries. Use response_mode="quotes" for short citable snippets or dry_run for diagnostics without passage text.
- Do not use for: `unindexed PubMed-only article fetching`
- Example: `{"review_id":"demo","queries":["EGFR resistance","osimertinib resistance"]}`
- Next tools by profile: lean: `pubtator.record_review_context`, `pubtator.get_review_audit_trail`; full: `pubtator.record_review_context`, `pubtator.get_review_audit_trail`; readonly: `pubtator.get_review_audit_trail`
- Resource links: `pubtator://reviews/{review_id}/llm-context`
- Output schema: `RetrieveReviewContextBatchResponse`; has_output_schema: `yes`

## `pubtator.review_quickstart`

- Name: `pubtator.review_quickstart`
- Title: Review Quickstart
- Category: `review`
- Profiles: `full`
- Stability: `advanced`
- Description: Use this when a user wants one-shot casual review setup: search topic, stage/index up to n_pmids, inspect coverage, and return review_id/session_id for retrieve_review_context_batch.
- Do not use for: `readonly deployments`
- Example: `{"topic":"EGFR resistance in lung cancer","n_pmids":8}`
- Next tools by profile: full: `pubtator.retrieve_review_context_batch`
- Resource links: None
- Output schema: `ReviewQuickstartResponse`; has_output_schema: `yes`

## `pubtator.search_biomedical_entities`

- Name: `pubtator.search_biomedical_entities`
- Title: Search Biomedical Entities
- Category: `discovery`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user needs canonical PubTator biomedical entity IDs for genes, diseases, chemicals, species, variants, or cell lines.
- Do not use for: `literature search by article topic`
- Example: `{"query":"TP53","concept":"Gene","limit":10}`
- Next tools by profile: lean: `pubtator.search_literature`; full: `pubtator.search_literature`; readonly: `pubtator.search_literature`
- Resource links: `pubtator://bioconcepts`
- Output schema: `EntityAutocompleteResponse`; has_output_schema: `yes`

## `pubtator.search_guidelines`

- Name: `pubtator.search_guidelines`
- Title: Search Biomedical Guidelines
- Category: `literature`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user needs guideline, recommendation, consensus, or systematic review papers for a biomedical research question. This is a convenience wrapper over pubtator.search_literature with guideline/systematic-review publication-type filters and guideline boosting, not an independent guideline database. Defaults to source coverage preflight so abstract-only guideline hits are visible before indexing.
- Do not use for: `non-guideline exhaustive PubMed search`
- Example: `{"text":"asthma treatment adults","limit":5}`
- Next tools by profile: lean: `pubtator.preflight_review_sources`; full: `pubtator.preflight_review_sources`; readonly: `pubtator.preflight_review_sources`
- Resource links: None
- Output schema: `SearchResponse`; has_output_schema: `yes`

## `pubtator.search_literature`

- Name: `pubtator.search_literature`
- Title: Search Biomedical Literature
- Category: `literature`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a user needs PubMed literature search through PubTator3. Supports short biomedical queries, flat filters, optional section filters, and coverage='preflight'. If preflight_error_code is coverage_preflight_internal_error, retryable=false means continue with results or inspect diagnostics.
- Do not use for: `fetching known PMID passage text`
- Example: `{"text":"BRCA1 ovarian cancer PARP inhibitor","limit":5,"metadata":"basic"}`
- Next tools by profile: lean: `pubtator.preflight_review_sources`; full: `pubtator.preflight_review_sources`; readonly: `pubtator.preflight_review_sources`
- Resource links: None
- Output schema: `SearchResponse`; has_output_schema: `yes`

## `pubtator.stage_research_session`

- Name: `pubtator.stage_research_session`
- Title: Stage Research Session
- Category: `review`
- Profiles: `full`
- Stability: `advanced`
- Description: Use this when a user needs to stage candidate PMIDs with coverage hints and queued review preparation after search planning.
- Do not use for: `readonly deployments`
- Example: `{"review_id":"demo","query":"BRCA1 PARP inhibitor","max_candidates":20}`
- Next tools by profile: full: `pubtator.get_research_session_status`, `pubtator.index_review_evidence`
- Resource links: `pubtator://reviews/{review_id}/sessions/{session_id}`
- Output schema: `StageResearchSessionResponse`; has_output_schema: `yes`

## `pubtator.submit_text_annotation`

- Name: `pubtator.submit_text_annotation`
- Title: Submit Text Annotation
- Category: `annotation`
- Profiles: `full`
- Stability: `advanced`
- Description: Use this when research text should be submitted for PubTator biomedical named entity recognition. Do not use this for PubMed or PMC IDs; use pubtator.fetch_publication_annotations. Next: pubtator.get_text_annotation_results.
- Do not use for: `PubMed or PMC ID annotation export`
- Example: `{"text":"BRCA1 is associated with breast cancer.","bioconcepts":"Gene,Disease"}`
- Next tools by profile: full: `pubtator.get_text_annotation_results`
- Resource links: `pubtator://text-processing`
- Output schema: `TextAnnotationSubmitResponse`; has_output_schema: `yes`

## `pubtator.suggest_corpus`

- Name: `pubtator.suggest_corpus`
- Title: Suggest Corpus
- Category: `discovery`
- Profiles: `full`, `readonly`
- Stability: `advanced`
- Description: Use this when a user needs a compact, review-feeding PMID corpus for a research question. Returns candidate PMIDs, roles, coverage hints, metadata, and next commands.
- Do not use for: `final evidence retrieval`
- Example: `{"question":"EGFR resistance in lung cancer","max_pmids":8}`
- Next tools by profile: full: `pubtator.preflight_review_sources`, `pubtator.index_review_evidence`; readonly: `pubtator.preflight_review_sources`
- Resource links: None
- Output schema: `CorpusSuggestionResponse`; has_output_schema: `yes`

## `pubtator.workflow_help`

- Name: `pubtator.workflow_help`
- Title: Workflow Help
- Category: `metadata`
- Profiles: `lean`, `full`, `readonly`
- Stability: `lean`
- Description: Use this when a fresh context needs the canonical PubTator-Link research workflow.
- Do not use for: `server capability inventory`
- Example: `{"task":"clinical_genetics_review"}`
- Next tools by profile: lean: `pubtator.search_literature`; full: `pubtator.search_literature`; readonly: `pubtator.search_literature`
- Resource links: `pubtator://workflow-help`
- Output schema: `WorkflowHelpResponse`; has_output_schema: `yes`
