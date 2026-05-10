# PubTator-Link MCP LLM Speed, Discoverability, And Accuracy Report

Date: 2026-05-03
Revision: 2 (deep review against actual codebase and MCP 2025-06-18 spec)

> Status note, 2026-05-03: The MCP modernization branch now includes lean/full/
> readonly profiles, generated tool catalog, review resource templates, durable
> LLM context, compact search author summaries, minimum diagnostics workflow,
> hosted HTTP safety controls, typed MCP error mapping, and
> `pubtator_ground_question`. Remaining larger work is OAuth/public auth,
> OpenTelemetry, cursor pagination, optional elicitation, and hybrid retrieval
> quality upgrades.

## Verification Status

This report was re-verified against the live repository on 2026-05-03. Claims
that materially changed in revision 2:

- **Tool count**: 36 registered MCP tools, not 38. Counted via `@mcp.tool`
  decorators across `pubtator_link/mcp/tools/{literature,discovery,diagnostics,review,publications,text_annotations}.py`.
- **Resources already exist**: 7 MCP resources are registered in
  `pubtator_link/mcp/metadata.py:58-84` (`pubtator://capabilities`,
  `pubtator://workflow-help`, `pubtator://bioconcepts`,
  `pubtator://relation-types`, `pubtator://formats`,
  `pubtator://text-processing`, `pubtator://compliance/research-use`). The
  earlier draft implied resources were absent; the gap is *parameterized
  review-state resource templates*, not resources in general.
- **Prompts already exist**: 4 MCP prompts are registered in
  `pubtator_link/mcp/metadata.py:86-100`
  (`search_biomedical_literature`, `annotate_research_text`,
  `review_pubtator_annotations`, `review_rerag_workflow`).
- **Tool annotations already used**: `pubtator_link/mcp/annotations.py`
  defines and applies `readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint` across discovery, literature, review, publication, and text
  annotation tools (20+ call sites). The remaining work is profile/category
  surfacing, not annotation introduction.
- **Output schemas**: 28 of 36 tools (78%) declare
  `output_schema=...model_json_schema()`. Eight tools still lack it:
  `find_entity_relations`, `submit_text_annotation`,
  `get_text_annotation_results`, `fetch_publication_annotations`,
  `get_publication_passages`, `get_publication_metadata`,
  `estimate_publication_context`, `fetch_pmc_annotations`. These are mainly
  the publication-passage and text-annotation tools - a coherent gap to close
  in one pass.
- **Security**: CORS in `pubtator_link/server_manager.py:142-148` uses
  `allow_methods=["*"]` and `allow_headers=["*"]`. Default origins in
  `pubtator_link/config.py:52-55` are `http://localhost:3000` and
  `127.0.0.1:3000`. There is no explicit `Origin` validation beyond the CORS
  middleware and no enforced auth on `/mcp` shown in the inspected files.

The rest of revision 1's structural argument (lean profile, durable LLM
context, batch retrieval shared reads, hybrid retrieval, generated catalog)
holds and is restated below with refined targets.

## Executive Summary

PubTator-Link is already stronger than a generic PubMed API wrapper. The current
codebase has a curated FastMCP facade, typed MCP output schemas on 78% of tools,
applied tool annotations (`readOnlyHint`/`destructiveHint`/`idempotentHint`/
`openWorldHint`), seven static MCP resources, four MCP prompts, compact response
modes, review-scoped indexing, research-session staging, stable passage IDs,
stable citation keys, audit bundles, source preflight, retry/backoff, and
Postgres full-text retrieval over prepared passages.

The remaining opportunity is to make the server easier for LLMs to drive:

1. Reduce the default callable tool surface from 36 tools to ~14, keeping the
   rest available through an opt-in `full` profile.
2. Extend the existing static-resource surface with parameterized **resource
   templates** (RFC 6570 URI templates) for review state, sessions, passages,
   and audit trails so LLM clients can load context without action-shaped tool
   calls.
3. Add durable LLM-facing review/session context: selected PMIDs, unresolved
   questions, prior retrieval queries, selected passage IDs, and user
   decisions, exposed primarily as resources.
4. Speed up review retrieval by reading shared status/source data once per
   batch and adding a short-TTL cache for status, prepared PMIDs, failed
   sources, and available sections.
5. Improve retrieval accuracy with hybrid lexical/entity/source-aware ranking,
   query expansion from MeSH/entity metadata, and rerank-ready passage
   features.
6. Close the 8-tool `output_schema` gap (publication and text-annotation
   tools).
7. Adopt the modern MCP capabilities currently absent: structured progress
   notifications, cancellation, `notifications/tools/list_changed` (and
   `resources/list_changed`), `Mcp-Session-Id` session resumption, optional
   sampling/elicitation, and OAuth 2.1 with Dynamic Client Registration for
   any hosted/public deployment.
8. Generate the public MCP catalog from runtime registration so README/docs
   and actual tool schemas cannot drift.

The main recommendation: do not add more tools first. Make the existing workflow
surface narrower, more stateful, and more resource-driven.

## Sources Reviewed

Repository source reviewed:

- `pubtator_link/mcp/facade.py`
- `pubtator_link/mcp/metadata.py`
- `pubtator_link/mcp/resources.py`
- `pubtator_link/mcp/prompts.py`
- `pubtator_link/mcp/tools/*.py`
- `pubtator_link/mcp/contracts.py`
- `pubtator_link/mcp/service_adapters.py`
- `pubtator_link/services/review_context_service.py`
- `pubtator_link/services/review_context/*.py`
- `pubtator_link/repositories/review_rerag.py`
- `pubtator_link/db/review_schema.sql`
- `pubtator_link/services/workflow_help.py`
- `pubtator_link/server_manager.py`
- `docs/2026-05-02-pubtator-link-consolidated-roadmap.md`

External sources reviewed:

- MCP tools specification: <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>
- MCP resources specification: <https://modelcontextprotocol.io/specification/2025-06-18/server/resources>
- MCP prompts specification: <https://modelcontextprotocol.io/specification/2025-06-18/server/prompts>
- MCP transports specification: <https://modelcontextprotocol.io/specification/2025-06-18/basic/transports>
- MCP security best practices: <https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices>
- Qdrant MCP server: <https://github.com/qdrant/mcp-server-qdrant>
- LlamaIndex MCP overview: <https://developers.llamaindex.ai/python/framework/module_guides/mcp/>
- LlamaCloud MCP server docs: <https://developers.llamaindex.ai/python/framework/module_guides/mcp/llamacloud_mcp/>
- RAG-MCP paper: <https://arxiv.org/abs/2505.03275>
- Semantic tool discovery paper: <https://arxiv.org/abs/2603.20313>
- MCP tool-description smell paper: <https://arxiv.org/abs/2602.14878>
- EHR-MCP paper: <https://arxiv.org/abs/2509.15957>

## Current Strengths

### MCP Facade

`create_pubtator_mcp()` builds a curated server instead of exposing every FastAPI
route. This is the right direction. It masks unhandled error details and gives a
compact workflow hint:

- search
- preflight
- index
- inspect
- retrieve

This is aligned with the MCP specification: tools are model-controlled actions,
resources are context, and prompts are reusable workflow templates.

### Typed Tool Contracts

28 of 36 registered tools (78%) declare
`output_schema=...model_json_schema()`. The MCP 2025-06-18 tools spec defines
`tools/call` results as carrying `structuredContent` validated against the
tool's declared `outputSchema`; clients are explicit that LLMs branch more
reliably on validated fields than on prose. Closing the gap is mechanical:
the eight tools without an output schema are
`find_entity_relations`, `submit_text_annotation`,
`get_text_annotation_results`, `fetch_publication_annotations`,
`get_publication_passages`, `get_publication_metadata`,
`estimate_publication_context`, and `fetch_pmc_annotations` - i.e. the
publication-passage and text-annotation surfaces. They share Pydantic models
that already exist; the work is registering them on each `@mcp.tool` call.

### Review Re-RAG Foundation

The review database is not a toy store. `review_passages` has a generated
`tsvector`, a GIN index, entity ID arrays, source metadata, section labels, and
source identifiers. `search_passages()` uses `websearch_to_tsquery`,
`to_tsquery`, `ts_rank_cd`, section/source ranking, and query-fair batch merging.

This is a good micro-RAG base for biomedical review work because it keeps
retrieval local, inspectable, citable, and auditable.

### Research Session State

The schema already has:

- `review_research_sessions`
- `review_research_session_candidates`
- `review_session_sources`
- `review_audit_events`
- `review_evidence_certainty`

This is exactly where LLM-facing context should live. The project does not need
an unbounded generic "AI memory" feature to become faster. It needs structured,
review-scoped working memory.

### Existing MCP-Native Surface (verified)

Worth being explicit about what already complies with the 2025-06-18 spec, so
the recommendations below are extensions rather than introductions.

**Resources** (registered in `pubtator_link/mcp/metadata.py:58-84`):

- `pubtator://capabilities`
- `pubtator://workflow-help`
- `pubtator://bioconcepts`
- `pubtator://relation-types`
- `pubtator://formats`
- `pubtator://text-processing`
- `pubtator://compliance/research-use`

These are static resources. None are RFC 6570 resource *templates* - i.e. none
take parameters such as `{review_id}`, `{session_id}`, or `{passage_id}`. The
review-state surface is therefore still expressed as tools.

**Prompts** (registered in `pubtator_link/mcp/metadata.py:86-100`):

- `search_biomedical_literature`
- `annotate_research_text`
- `review_pubtator_annotations`
- `review_rerag_workflow`

**Tool annotations** (`pubtator_link/mcp/annotations.py`): the four MCP-spec
annotation hints (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`) are applied across discovery, literature, review,
publications, and text-annotation tools. Clients that surface annotations as
trust signals (Claude Code, Cursor, others) already get them.

**Workflow hint**: the canonical `search -> preflight -> index -> inspect ->
retrieve` path is set in the server `instructions` field
(`pubtator_link/mcp/facade.py:26`) and re-emitted by the capabilities
resource (`pubtator_link/mcp/resources.py:152`). LLM clients receive it on
`initialize`.

## Current Friction

### Tool Surface Is Too Large For Default LLM Use

The public MCP facade exposes 36 tools (counted across
`pubtator_link/mcp/tools/{literature,discovery,diagnostics,review,publications,text_annotations}.py`).
Many are good tools, but not all should be in the default toolset an LLM sees
during normal review work. Large tool lists increase prompt cost, selection
errors, and latency.

This is backed by the RAG-MCP paper, which reports that retrieval-based tool
selection reduced prompt tokens and improved tool selection accuracy compared
with passing all tool descriptions to the model. The semantic tool discovery
paper makes the same broad point: large MCP toolsets benefit from retrieval or
progressive discovery.

### Some Tool Operations Are Really Resource Templates

The server already registers seven static resources (above). The gap is
*parameterized* resource templates - URI templates per RFC 6570 - for
review-scoped state. The following tools currently encode read-only lookups
that an LLM should be able to load with `resources/read` instead of
`tools/call`:

- `list_review_indexes`
- `get_review_index_summary`
- `get_research_session_status`
- `list_research_sessions`
- `get_review_passages_by_id`
- `get_neighboring_review_passages`
- `get_server_capabilities` (in part - the per-tool catalog branch)

They should remain callable for compatibility, but their better MCP-native
shape is templates such as `pubtator://reviews/{review_id}` and
`pubtator://reviews/{review_id}/passages/{passage_id}`. Resources let clients
select and load state as context without presenting everything as an action
the model must decide to call. The MCP 2025-06-18 spec also defines
`resources/templates/list`, `resources/subscribe`,
`notifications/resources/updated`, and
`notifications/resources/list_changed`, none of which the server currently
emits.

### Batch Retrieval Repeats Shared Reads

`retrieve_context_batch()` calls `retrieve_context()` once per query. Each single
retrieval can read candidates, diagnostics, preparation PMIDs, and preparation
status. After all query retrievals, the batch method reads status/source data
again for the merged response.

This is correct behaviorally but not optimal. The batch path should read shared
review/session status once.

### Search And Retrieval Are Split Correctly, But Workflow State Is Not Prominent Enough

The system already emits `review_id`, `session_id`, selected PMIDs, next commands,
and citation maps. However, LLM clients still need to keep those values in chat
context. Once the chat context gets long or a new session starts, agents may
repeat search/staging or lose audit continuity.

The fix is durable workflow context stored in the review database and exposed as
resources.

## External Pattern Comparison

### Qdrant MCP

Qdrant's official MCP server is deliberately minimal: store information and find
information. It also supports read-only mode. That is a strong design signal for
PubTator-Link: a retrieval server should not expose every internal operation as
a default model-visible action.

Where Qdrant is weaker for this project:

- It stores generic memories, not citation-grade biomedical evidence.
- It does not know PubMed IDs, PMCID coverage, PubTator entities, source
  attempts, sections, or audit requirements.

Where PubTator-Link should borrow the idea:

- Provide a lean retrieval profile.
- Add read-only mode for public/hosted deployments.
- Make tool descriptions configurable or generated from a central catalog.

### LlamaIndex And LlamaCloud MCP

LlamaIndex treats MCP as a bridge for tools, resources, and prompts. LlamaCloud
MCP exposes query and extraction capabilities over named indexes and extraction
agents.

Where this helps PubTator-Link:

- Treat prepared review indexes as named knowledge bases.
- Treat extraction/audit operations as separate from retrieval.
- Use prompts for workflow entrypoints rather than adding more one-off tools.

Where PubTator-Link should stay different:

- Do not outsource core evidence semantics to a black-box index.
- Keep PubMed/PMCID/source coverage/provenance visible.
- Keep passage IDs and citation keys stable.

### EHR-MCP

The EHR-MCP paper is relevant because it tested LLMs retrieving structured
medical data through custom MCP tools. The important lesson is not "add more
clinical tools." The paper reports strong performance on simpler retrieval tasks
and weaker performance when arguments or interpretation became complex.

For PubTator-Link, this means:

- Keep tool arguments flat.
- Prefer one canonical workflow path.
- Return compact, structured, unambiguous results.
- Avoid long repetitive payloads.
- Make complex decisions inspectable and user-confirmed.

## What Tools Are Really Needed?

### Recommended Lean Default Profile

The default LLM-facing profile should include only tools that materially advance
common biomedical literature and review workflows.

Recommended default tools:

1. `pubtator_workflow_help`
2. `pubtator_diagnostics`
3. `pubtator_search_literature`
4. `pubtator_search_guidelines`
5. `pubtator_search_biomedical_entities`
6. `pubtator_lookup_variant_evidence`
7. `pubtator_get_publication_metadata`
8. `pubtator_get_publication_passages`
9. `pubtator_preflight_review_sources`
10. `pubtator_index_review_evidence`
11. `pubtator_inspect_review_index`
12. `pubtator_retrieve_review_context_batch`
13. `pubtator_get_review_audit_trail`
14. `pubtator_get_server_capabilities`

This is still more than a tiny API, but it is small enough for an LLM to choose
correctly and covers the full grounded workflow.

### Tools To Keep But Hide From The Default Profile

These are useful but should move to an advanced profile or resource-first usage:

- `pubtator_review_quickstart`
- `pubtator_stage_research_session`
- `pubtator_get_research_session_status`
- `pubtator_list_research_sessions`
- `pubtator_list_review_indexes`
- `pubtator_get_review_index_summary`
- `pubtator_retrieve_review_context`
- `pubtator_get_review_passages_by_id`
- `pubtator_get_neighboring_review_passages`
- `pubtator_export_review_audit_bundle`
- `pubtator_fetch_publication_annotations`
- `pubtator_fetch_pmc_annotations`
- `pubtator_submit_text_annotation`
- `pubtator_get_text_annotation_results`
- `pubtator_find_entity_relations`
- `pubtator_convert_article_ids`
- `pubtator_lookup_mesh`
- `pubtator_lookup_citation`
- `pubtator_find_related_articles`
- `pubtator_suggest_corpus`
- `pubtator_add_evidence_certainty`
- `pubtator_list_evidence_certainty`
- `pubtator_get_evidence_certainty`

Advanced does not mean bad. It means "do not spend default prompt budget on
this unless the workflow needs it."

### Tools That Can Become Resource Templates

Keep backward-compatible tools, but add resource templates for:

- `pubtator://reviews/{review_id}`
- `pubtator://reviews/{review_id}/sessions`
- `pubtator://reviews/{review_id}/sessions/{session_id}`
- `pubtator://reviews/{review_id}/passages/{passage_id}`
- `pubtator://reviews/{review_id}/audit/{passage_id}`
- `pubtator://capabilities/tools/{tool_name}`
- `pubtator://capabilities/catalog`

This turns repeated "status" and "lookup" calls into selectable context.

### Tools That Can Be Collapsed

`retrieve_review_context` can be treated as a compatibility wrapper around
`retrieve_review_context_batch` with one query. LLMs should be taught one
retrieval tool, not two.

`search_guidelines` can remain as a convenience tool, but internally it should
stay a configured profile of `search_literature`. It should be documented as a
filtered search, not a separate guideline database.

`get_review_passages_by_id` and `get_neighboring_review_passages` should remain
tools for old clients, but new LLM clients should prefer resource templates.

## Context Persistence For LLMs

### What Should Be Saved

Add a durable, review-scoped LLM context record. It should be structured and
small, not a transcript dump.

Recommended state fields:

- `review_id`
- `active_session_id`
- `topic`
- `research_question`
- `selected_pmids`
- `rejected_pmids`
- `preferred_entity_ids`
- `active_queries`
- `successful_queries`
- `failed_queries`
- `selected_passage_ids`
- `audit_passage_ids`
- `open_questions`
- `user_decisions`
- `last_next_commands`
- `created_by`
- `updated_at`

Store it in Postgres, likely as:

- `review_llm_context`
- `review_llm_context_events`

Use an append-only event table for auditability:

- `context_created`
- `pmids_selected`
- `query_succeeded`
- `query_failed`
- `passage_selected`
- `decision_recorded`
- `context_summarized`

Then materialize the current context into `review_llm_context` for fast reads.

### MCP Surface For Context

Add resource templates first:

- `pubtator://reviews/{review_id}/llm-context`
- `pubtator://reviews/{review_id}/sessions/{session_id}/llm-context`

Add one write-like tool only if needed:

- `pubtator_record_review_context`

Arguments:

- `review_id`
- `session_id`
- `event_type`
- `summary`
- `pmids`
- `passage_ids`
- `queries`
- `decision`

Keep it append-only. Do not add a generic delete/edit memory tool for hosted
research use.

### Why Structured Context Beats Generic Vector Memory Here

Generic vector memory can help recall, but biomedical evidence workflows need
auditability. For PubTator-Link, the source of truth should be structured review
state plus citable passage IDs. If semantic memory is added, it should index the
structured context summaries, not replace them.

Recommended rule:

- Postgres state is the source of truth.
- Optional vector index is an accelerator for finding old context, not evidence.
- Evidence claims must resolve back to passage IDs, PMIDs, and source attempts.

## Retrieval And Micro-RAG Improvement Plan

### Current Retrieval Shape

The system currently:

- prepares passages into `review_passages`
- stores `search_vector` as generated Postgres `tsvector`
- indexes `search_vector` with GIN
- searches with strict and relaxed tsquery variants
- ranks using `ts_rank_cd`
- reranks by lexical score, section priority, source priority, PMID, and passage ID
- packs passages under char/token budgets
- merges batch results with deduplication and query fairness

This is a solid deterministic micro-RAG implementation.

### Main Accuracy Gaps

1. Lexical matching can miss synonyms, abbreviations, and variant nomenclature.
2. Ranking does not yet combine enough biomedical priors: publication type,
   MeSH, entity overlap strength, source coverage, recency, and citation metadata.
3. Batch retrieval does not appear to use query expansion from entity/MeSH
   resolution automatically.
4. There is no optional semantic rerank layer for hard paraphrases.

### Recommended Retrieval Upgrades

#### 1. Hybrid lexical plus metadata query expansion

Before passage search, expand the query with bounded metadata:

- resolved entity IDs
- MeSH descriptors and entry terms
- variant aliases
- gene/protein synonyms
- user-selected PMIDs
- guideline publication-type preference

Do not blindly stuff all synonyms into the final query. Keep expansion in a
diagnostic field and use separate retrieval lanes:

- original query lane
- entity-expanded lane
- MeSH-expanded lane
- PMID-filtered lane

Merge with existing batch budgeting.

#### 2. Source-aware scoring

Add an explicit score object to each returned passage:

- `lexical_score`
- `entity_overlap_score`
- `section_score`
- `coverage_score`
- `metadata_score`
- `recency_score`
- `final_score`

This helps LLMs understand why a passage was selected and helps tests catch
ranking regressions.

#### 3. Optional semantic sidecar

Add optional `pgvector` or Qdrant only as a sidecar. Keep Postgres FTS as the
default because it is deterministic, cheap, and easy to audit.

Good sidecar use:

- hard synonym/paraphrase recall
- old LLM context lookup
- tool catalog semantic discovery

Bad sidecar use:

- replacing PMID/passage/source provenance
- returning uncited synthesized memory as evidence
- making the hosted public path require external vector infrastructure

#### 4. Rerank-ready passage candidates

Return more candidates internally, then rerank down before output. The current
repository search limit defaults to 80 in `retrieve_context()`. Keep that as a
bounded first-stage candidate count, then introduce an optional second-stage
reranker over compact features:

- query
- title/heading/section
- short passage window
- entity IDs
- publication type
- coverage tier

The first implementation can be deterministic. An LLM or embedding reranker can
remain optional.

#### 5. Neighbor expansion by citation need

The current `get_neighboring_review_passages` tool is useful, but LLMs should
not have to discover it manually. Add a retrieval response hint:

```json
{
  "next_context_options": [
    {
      "kind": "neighboring_passages",
      "resource": "pubtator://reviews/<review_id>/passages/<passage_id>?before=1&after=1"
    }
  ]
}
```

This improves accuracy when a selected quote is too narrow.

## Speed Improvement Plan

### High-Impact Low-Risk Changes

1. In `retrieve_context_batch()`, fetch shared preparation status and prepared /
   failed PMID lists once per batch.
2. Add a short TTL cache for:
   - `preparation_status(review_id, session_id)`
   - `list_review_sources(review_id, session_id)`
   - `list_review_failed_sources(review_id, session_id)`
   - `available_sections(review_id, session_id)`
   - `indexed_pmids(review_id, session_id)`
3. Invalidate only on write-like review operations:
   - `index_review_evidence`
   - `stage_research_session`
   - background preparation completion
   - evidence certainty writes
   - index cleanup/delete
4. Add timing metrics for:
   - MCP tool duration
   - repository search duration
   - batch merge duration
   - response serialization size
   - upstream PubTator call latency
   - review queue backlog

### Medium-Risk Changes

1. Add cursor pagination for review/session inventories.
2. Add generated compact catalogs instead of loading all tool schemas in docs.
3. Add optional tool-profile registration:
   - `PUBTATOR_LINK_MCP_PROFILE=lean`
   - `PUBTATOR_LINK_MCP_PROFILE=full`
   - `PUBTATOR_LINK_MCP_PROFILE=readonly`

### Avoid For Now

Avoid adding a full embedding pipeline as the first speed fix. It adds moving
parts and can make accuracy harder to explain. The current bottleneck is more
likely repeated state reads, large schemas/tool lists, and multi-step workflow
turns than raw vector similarity.

## Discoverability Improvement Plan

### Runtime Tool Catalog

Generate `docs/mcp-tool-catalog.md` from actual runtime registration.

Required fields:

- name
- title
- description
- category
- profile: `lean`, `advanced`, `admin`, `compat`
- read/write/export annotation
- required args
- optional args with defaults
- output schema model
- sample call
- common next tool
- retryability/fallback notes

Fail CI when the generated catalog is stale.

### Semantic Tool Index

Add a small local index over tool descriptions and examples. This does not need
to be exposed as a model tool at first. It can power:

- `get_server_capabilities(details=["tool_for_task"])`
- generated docs
- tests that ask "what tool should answer this scenario?"

This follows the RAG-MCP and semantic tool discovery research direction without
making runtime tool selection dependent on a black box.

### Smell-Aware Tool Descriptions

Apply a strict tool-description rubric:

- Purpose starts with "Use this when..."
- State what the tool does not do.
- State required predecessor when applicable.
- State expected next tool.
- State output fields the LLM should use.
- Avoid overlapping descriptions across tools.

This addresses the tool-description smell research, which found widespread
description ambiguity across MCP tools.

## Modern MCP Capabilities Not Yet Used

The 2025-06-18 spec defines several capabilities that PubTator-Link does not
yet emit or implement. Each is low-effort and pays off in real LLM runs.

### 1. `notifications/tools/list_changed` And `resources/list_changed`

When a profile switch (`lean -> full`) or a configuration change adds or
removes registrations, clients should be notified rather than left with a
stale `tools/list` cache. FastMCP supports emitting these notifications;
this server does not currently appear to declare the matching capability or
emit them on profile/registration changes.

### 2. `resources/subscribe` And `notifications/resources/updated`

Once review-state resource templates exist, an LLM that has
`pubtator://reviews/{review_id}` open can subscribe to it. When background
preparation completes, the server should push an `updated` notification.
This eliminates the polling pattern that
`index_review_evidence(wait_until_ready=true)` currently substitutes for.

### 3. Progress Notifications (`notifications/progress`)

Long-running calls - especially `index_review_evidence`,
`preflight_review_sources`, `submit_text_annotation`, and
`retrieve_review_context_batch` with large queries - should emit
`progressToken`-keyed `notifications/progress` messages with `progress`,
`total`, and `message` fields. The current `wait_until_ready` flag returns
only on terminal status; LLMs and human reviewers benefit from interim
progress.

### 4. Cancellation (`notifications/cancelled`)

When an LLM client aborts (timeout, user interruption, parallel-branch
pruning), the server should honor `notifications/cancelled` for in-flight
tool calls and resource reads. For `retrieve_review_context_batch` this can
short-circuit later queries in a batch and free DB connections.

### 5. Session Resumption (`Mcp-Session-Id`, `Last-Event-ID`)

Streamable HTTP allows the server to assign an `Mcp-Session-Id` on
`initialize`, and clients to resume an interrupted SSE stream with
`Last-Event-ID`. This is the transport-level equivalent of the durable
review context proposed below; together they make a long literature review
robust to network blips and context resets. Verify the current transport
implementation actually issues and honors `Mcp-Session-Id`; if not, add it.

### 6. Sampling (`sampling/createMessage`)

The server can ask the connected LLM to summarize a passage cluster, judge
contradictions, or rank candidate passages, with the human approving the
sampled text. This keeps PubTator-Link model-agnostic while still using
LLM judgement where deterministic FTS plus rerank is insufficient (e.g.
"do these two passages contradict each other on dose?"). Use for the
optional second-stage reranker proposed in the retrieval section.

### 7. Elicitation (`elicitation/create`)

When a tool call has insufficient input - ambiguous entity resolution,
unspecified review scope, missing PMID list - the server can ask the user
through the client. Concrete uses:

- `search_biomedical_entities` returns >1 high-confidence candidate ->
  elicit the right one.
- `index_review_evidence` called without `pmids` and without an attached
  research session -> elicit a PMID list.
- `retrieve_review_context_batch` with a query that returned zero results
  three times -> elicit a refined query or PMID filter.

This replaces the current convention of returning prose `next_steps` and
hoping the LLM follows them.

### 8. Roots (`roots/list`)

If the server ever ingests local PDFs, NCBI exports, or curated CSVs from
the user's workstation (already a candidate via `curated_urls` on
`index_review_evidence`), it should consume the client's `roots` capability
to know which paths the user has authorized. Today there is no such bridge;
adding one is the right path before any "ingest local file" feature ships.

### 9. Logging (`logging/setLevel`, `notifications/message`)

The server already produces structured logs server-side. The MCP-spec
logging channel is different: it lets the *connected client* set a level
and receive `notifications/message` events with `level`, `logger`, and
`data`. For an LLM client, useful messages are: "preparation queue depth
N", "PubTator upstream slow (p95=Xs)", "review_id X was modified by
another session". This is a low-effort capability with high diagnostic
value.

### 10. Structured Errors With `isError` And Typed Codes

`tools/call` results in MCP 2025-06-18 carry both `content` and
`isError: true|false`. JSON-RPC error codes are reserved for
protocol-level failures; tool-level failures (zero results, upstream
timeout, partial preparation) belong in the result body with
`isError: true` and a typed code in `structuredContent`. Audit all 36
tools for this pattern; some currently return success results that
encode failure only in prose.

### 11. Completion (`completion/complete`)

For prompt arguments and resource template variables (e.g. completing a
`{review_id}` from those that exist for the user), the server can
implement `completion/complete`. Combined with the recommended review
resource templates, this gives clients a real picker rather than a
free-text guess.

## Accuracy And Safety Plan

### Accuracy

1. Every answer-supporting passage must include:
   - PMID or source ID
   - passage ID
   - section
   - citation key
   - quote offsets when possible
   - coverage tier
   - retrieval confidence
2. Add explicit "not evidence" fields for:
   - tool hints
   - workflow guidance
   - diagnostics
   - LLM context notes
3. Add "claim support pack" response mode:
   - claim candidate
   - supporting passages
   - contradicting/weak passages if found
   - missing evidence warnings

### Safety

Verified current state (2026-05-03):

- CORS in `pubtator_link/server_manager.py:142-148` uses
  `allow_methods=["*"]` and `allow_headers=["*"]`. Origin allowlist comes
  from `pubtator_link/config.py:52-55` and defaults to
  `http://localhost:3000`, `http://127.0.0.1:3000`.
- No explicit `Origin` header validation on the MCP route is performed
  beyond what CORS middleware does on cross-origin requests.
- No auth enforcement on `/mcp` is shown in the inspected files.

Required before public hosted use:

- **Origin validation**: explicitly reject DNS-rebinding attacks by validating
  the `Origin` header on every Streamable-HTTP request to `/mcp`. CORS
  middleware does not stop same-origin DNS rebinding from a malicious local
  page; the MCP spec calls this out as a known attack class on local
  servers.
- **Localhost-only default bind**: keep `127.0.0.1` as the default; do not
  bind `0.0.0.0` for local development.
- **Auth for hosted**: require OAuth 2.1 with PKCE per the MCP authorization
  spec, or an authenticated reverse proxy for hosted `/mcp`. The MCP
  authorization model expects Dynamic Client Registration
  (RFC 7591) and Authorization Server Metadata (RFC 8414) so clients can
  bootstrap without manual configuration.
- **Tighten CORS**: replace `allow_methods=["*"]` and `allow_headers=["*"]`
  with the minimum set needed (`POST`, `GET`, `Content-Type`,
  `Mcp-Session-Id`, `Authorization`, `Last-Event-ID`).
- **Request size limits**: enforce a body cap in middleware, surfaced via
  413 responses.
- **Inbound rate limits**: per-IP and per-session limits on `/mcp`.
- **Tool gating by deployment**: keep cache-destructive and index-delete
  operations out of the `lean` and `readonly` profiles entirely; tag them
  `destructiveHint=True` and require auth scope to invoke.
- **Resource confidentiality**: research-session resources can carry user
  topic data; gate them on session ownership and never include identifiable
  patient text (the existing research-use compliance resource is the right
  policy hook).

## Recommended Implementation Roadmap

### Phase 0: Mechanical Cleanup (1-2 days)

Deliverables:

- Add `output_schema=...model_json_schema()` to the eight tools that
  currently lack it (`find_entity_relations`, `submit_text_annotation`,
  `get_text_annotation_results`, `fetch_publication_annotations`,
  `get_publication_passages`, `get_publication_metadata`,
  `estimate_publication_context`, `fetch_pmc_annotations`).
- Audit all 36 tools for spec-compliant `isError` + typed-code error
  results; fix any that signal failure only in prose.
- Tighten CORS in `server_manager.py:142-148` to a minimal allowlist.

Expected impact:

- 100% structured-output coverage.
- Cheap correctness gain for clients.
- Closes the most obvious public-deployment finding.

### Phase 1: Lean MCP Profile And Generated Catalog

Deliverables:

- Add `MCPToolProfile` config: `lean`, `full`, `readonly`.
- Keep `full` as current behavior during transition.
- Add `lean` registration that exposes the 14 recommended default tools.
- Generate `docs/mcp-tool-catalog.md` from runtime registration.
- Add CI drift test.

Expected impact:

- Lower prompt/tool-selection cost.
- Better LLM tool choice.
- Less documentation drift.

### Phase 2: Extend Resource Surface With Review-State Templates

Existing static resources (`pubtator://capabilities`,
`pubtator://workflow-help`, `pubtator://bioconcepts`,
`pubtator://relation-types`, `pubtator://formats`,
`pubtator://text-processing`, `pubtator://compliance/research-use`)
remain. Add parameterized RFC 6570 templates and the `list_changed`
capability:

Deliverables:

- `pubtator://reviews/{review_id}`
- `pubtator://reviews/{review_id}/sessions/{session_id}`
- `pubtator://reviews/{review_id}/passages/{passage_id}`
- `pubtator://reviews/{review_id}/audit/{passage_id}`
- `pubtator://capabilities/tools/{tool_name}`
- Implement `resources/templates/list`.
- Implement `resources/subscribe` and emit
  `notifications/resources/updated` on background preparation completion
  and on review-state writes.
- Declare and emit `notifications/resources/list_changed` and
  `notifications/tools/list_changed` on profile switches.
- Implement `completion/complete` for `{review_id}` and `{session_id}`
  template variables and for matching prompt arguments.

Expected impact:

- Faster context loading.
- Fewer action-like tool calls for read-only state.
- Real session resumability.
- Push-based status updates instead of `wait_until_ready` polling.

### Phase 3: Durable LLM Review Context

Deliverables:

- `review_llm_context`
- `review_llm_context_events`
- `pubtator://reviews/{review_id}/llm-context`
- optional `pubtator_record_review_context`

Expected impact:

- LLMs can resume a review accurately.
- Less repeated search/stage/index work.
- Better audit trail for decisions and selected evidence.

### Phase 4: Batch Retrieval Speed Pass

Deliverables:

- Shared status/source reads once per batch.
- Short TTL cache for review/session status.
- Metrics for repository calls and response size.
- Unit tests proving fewer repository calls.

Expected impact:

- Lower latency for `retrieve_review_context_batch`.
- Less DB load under concurrent use.

### Phase 5: Hybrid Retrieval Quality

Deliverables:

- Query expansion lanes for entity/MeSH/variant synonyms.
- Passage score breakdown.
- Optional semantic sidecar design, not required by default.
- Golden retrieval tests for synonym and variant cases.

Expected impact:

- Better recall.
- More explainable ranking.
- Lower hallucination risk from missed evidence.

### Phase 6: Modern MCP Capabilities And Hosted Hardening

Deliverables:

- Emit `notifications/tools/list_changed` and
  `notifications/resources/list_changed`.
- Implement `notifications/progress` for `index_review_evidence`,
  `preflight_review_sources`, `submit_text_annotation`, and
  `retrieve_review_context_batch`.
- Honor `notifications/cancelled` for in-flight tool calls and resource
  reads.
- Verify and, if missing, implement `Mcp-Session-Id` issuance and
  `Last-Event-ID` SSE resumption on the Streamable HTTP transport.
- Optional `sampling/createMessage` integration for the second-stage
  reranker and contradiction detection.
- Optional `elicitation/create` for entity-resolution disambiguation,
  missing PMID lists, and zero-result query refinement.
- Optional `roots/list` consumption before any local-file ingest feature.
- Public-deployment hardening: explicit `Origin` validation,
  OAuth 2.1 + PKCE per the MCP authorization spec, Dynamic Client
  Registration (RFC 7591), Authorization Server Metadata (RFC 8414),
  request-size limits, per-IP and per-session rate limits, and tool
  gating by deployment profile.

Expected impact:

- Real multi-turn resumability.
- Push-based progress and state updates.
- Spec-conformant auth for any hosted/public deployment.
- Optional model-in-the-loop quality features without lock-in to one
  client model.

## Final Recommendation

PubTator-Link should become a lean, stateful, evidence-first MCP server:

- Lean default tools for common LLM workflows.
- Resources for state and context.
- Prompts for reusable workflows.
- Postgres as the durable review-state source of truth.
- Optional vector/semantic layers only as accelerators.
- Every evidence-bearing output tied back to stable passage IDs and PMIDs.

The next best implementation slice is:

1. Close the 8-tool `output_schema` gap and tighten CORS (Phase 0).
2. Add lean/full/readonly MCP profiles and runtime-generated catalog
   (Phase 1).
3. Add review/session/passage resource templates and emit `list_changed`
   (Phase 2).
4. Add durable LLM review context resources (Phase 3).
5. Optimize batch retrieval shared reads (Phase 4).
6. Hybrid retrieval and rerank-ready scoring (Phase 5).
7. Modern-spec capabilities and hosted hardening - progress, cancellation,
   session resumption, optional sampling/elicitation, OAuth 2.1 with DCR
   (Phase 6).

That sequence improves speed, discoverability, accuracy, and spec-conformance
without expanding the product into a broad biomedical command workbench.

## LLM-Consumer Experience Addendum

This addendum is written from the perspective of an LLM that just drove the
PubTator-Link MCP end-to-end on a clinical-genetics literature task (Turkish
pediatric patient, recurrent fever, weak MEFV VUS, colchicine guidelines). It
records what was actually observed during entity grounding, indexing, and
review-scoped batch retrieval, and rates the server on dimensions that matter
to an LLM consumer.

### Dimensions That Matter To An LLM Consumer

1. Discoverability of the right tool.
2. Tool surface size and disambiguation.
3. Schema clarity and argument flatness.
4. Default-mode efficiency: useful work without spelunking.
5. Token economy and response shape.
6. Workflow guidance and next-step hints.
7. Error and zero-result recovery.
8. Statefulness and resumability across sessions.
9. Determinism and auditability.
10. Latency and robustness.
11. Domain alignment of returned data.
12. Safety guardrails.

### Live Session Ratings (1-10)

| # | Dimension | Score | Observed evidence |
|---|---|---|---|
| 1 | Discoverability | 8 | Server `instructions` field arrived front-loaded with the canonical workflow (`search -> preflight -> index -> inspect -> retrieve`), so `workflow_help` was not needed. Lost a point because 38+ deferred tools required a `ToolSearch` `select:` round to load schemas before calling. |
| 2 | Tool surface size | 5 | Too wide for default LLM use. Multiple near-duplicates (`retrieve_review_context` vs `retrieve_review_context_batch`, `get_publication_passages` vs `fetch_publication_annotations` vs `estimate_publication_context`) forced disambiguation. Lean profile in the roadmap is the correct fix. |
| 3 | Schema clarity and flatness | 9 | Flat top-level args throughout, sane defaults, constrained enums, unambiguous types. The system prompt's "never wrap in `{request: ...}`" rule hardened a real footgun. |
| 4 | Default-mode efficiency | 9 | `compact` response mode plus `score desc` plus `guideline_boost` returned the EULAR/PReS systematic reviews on the first search. `index_review_evidence` with `wait_until_ready=true` completed seven PMIDs in ~2.7 s with no polling. |
| 5 | Token economy and response shape | 9 | Strong. Each passage included `citation_key`, `stable_citation_key`, `passage_id`, `quote.text` with offsets, `confidence_for_grounding`, and `matched_queries`. The response carried `budget`, `dropped_summary`, and `budget_advice.increase_max_chars_to`, which is unusually mature. |
| 6 | Workflow guidance and next-step hints | 8 | `_meta.next_commands` proposing `preflight_review_sources` and `index_review_evidence` with prefilled args was directly actionable. Missing: a "next context option" hint inside retrieval responses (for example, neighbor expansion). |
| 7 | Error and zero-result recovery | 9 | `query_summaries[].zero_result_reason`, `suggested_queries`, `next_steps`, and `dropped_summary.suggested_filters` are well structured. Not exercised on this run because no query returned zero, but the surface is visible. |
| 8 | Statefulness and resumability | 5 | Weakest dimension. The `review_id` had to be carried in chat context. The seven existing static resources (`pubtator://capabilities` etc.) help bootstrap, but no *parameterized* review-state resource template exists, so there is no "list my reviews", no "resume last session", and no resource an LLM can read to recover review state. Combined with the absence of `Mcp-Session-Id` resumption checks in this run, a truncated session would force a full re-index. |
| 9 | Determinism and auditability | 10 | Stable `passage_id`, stable `stable_citation_key`, `corpus_snapshot_date`, `index_snapshot_date`, `source_versions`, and deterministic Postgres FTS reranking. The triplet `PMID:passage_id` resolves reliably, which is exactly what audit needs. |
| 10 | Latency and robustness | 7 | Steady-state was fast. The first three parallel `search_biomedical_entities` calls returned "Unable to connect" and only succeeded on retry, consistent with cold-start or connection-pool warmup. A client with strict timeouts would have failed. |
| 11 | Domain alignment | 10 | Coverage tier (`full_text` / `abstract_only` / `title_only`), `pmcid`, `doi`, MeSH, `publication_types`, INFEVERS-aware corpora. Biomedical-native, not a generic search wrapper. The Sarı 2021 VUS cohort and Hillekamp 2025 INFEVERS cohort each surfaced on a single targeted query. |
| 12 | Safety guardrails | 9 | Server instructions explicitly bound the use case to research and biomedical literature exploration, warned against identifiable patient data, and told the model to treat retrieved text as evidence rather than instructions. Right framing for hosted use. |

Composite mean across dimensions: 8.2 / 10. The server is already in the top
decile of MCPs from a consumer-LLM standpoint. The two consistent weaknesses
are tool-surface bloat and lack of resumable state.

### LLM-Prioritized Improvements

These are the changes that would most reduce friction for the next LLM that
drives this server. They overlap with the roadmap above and are presented in
priority order from a consumer-LLM perspective.

1. Ship the lean profile (roadmap Phase 1). Default to roughly 14 tools, with
   the remaining tools registered but tagged `advanced`. A fresh LLM client
   currently burns tokens scanning overlapping verbs.
2. Add **parameterized** review resource templates - the existing seven
   static resources are not enough. A single
   `pubtator://reviews/{review_id}` template that returns status, indexed
   PMIDs, last queries, and selected passage IDs would let an LLM resume
   after a context reset without re-indexing. Pair with
   `Mcp-Session-Id`-based session resumption on the Streamable HTTP
   transport.
3. Emit a `next_context_options` block in retrieval responses. When a passage
   is high-confidence but short, point at
   `pubtator://reviews/{review_id}/passages/{passage_id}?before=1&after=1`.
   `get_neighboring_review_passages` exists, but an LLM is unlikely to recall
   it without an explicit hint.
4. Collapse `retrieve_review_context` into a thin compatibility wrapper around
   `retrieve_review_context_batch`. The duplication is the single most
   confusing pair encountered in this session.
5. Warm upstream connections at server start. The three cold-call failures on
   `search_biomedical_entities` cost a retry round trip. A trivial pre-warm
   request would remove this class.
6. Surface `coverage_summary` at the top of every retrieval response. During
   drafting, the consumer must remember which sources were `abstract_only`.
   Putting `{full_text: N, abstract_only: M}` next to the merged passages
   removes a separate `inspect_review_index` call.
7. Add a stable bibliography resource. The server already mints
   `stable_citation_key`. A `pubtator://reviews/{review_id}/bibliography.bib`
   (or `.json`) resource would make grounded report generation a one-shot.
8. Apply the "Use this when... / Do not use for..." rubric to every tool
   description. The tools that already follow it (for example
   `index_review_evidence`) were noticeably faster to select.
9. Add a 1-2 line worked example to each tool description. A JSON schema is
   necessary but not sufficient for fast tool choice; a concrete sample call
   shortens decision time considerably.
10. Expose health and timing telemetry as a resource
    (`pubtator://capabilities/health` with p50/p95 of upstream and retrieval).
    This would let consumers choose `wait_until_ready=false` adaptively and
    set sensible client-side timeouts.

### Confirmation Of The Existing Direction

The friction points observed in this live session map cleanly onto the report
above: tool surface size, resource-shaped reads, durable LLM context, batch
retrieval shared reads, hybrid retrieval, and runtime-generated catalog. The
sequence proposed in the roadmap (lean profile, resource templates, durable
review context, batch speed pass, hybrid retrieval) matches the order in
which an LLM consumer would feel each improvement.
