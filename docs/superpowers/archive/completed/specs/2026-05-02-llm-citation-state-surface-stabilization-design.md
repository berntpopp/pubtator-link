# LLM Citation And State Surface Stabilization Design

Date: 2026-05-02

## Purpose

Recent LLM-consumer evaluations show that PubTator-Link's review workflow is
strong, but a few surface-level gaps still force consuming agents into avoidable
degradation:

- missing author and citation metadata,
- pessimistic source preflight hints,
- trivial review index samples,
- incomplete index snapshot metadata,
- coarse polling hints,
- broad tool discovery overhead,
- repeated manual corpus construction across similar biomedical review tasks.

This design specifies a broader ergonomics sprint that fixes those issues while
preserving the existing review-scoped evidence architecture.

## Goals

- Complete the citation metadata contract for LLM-generated bibliographies.
- Make source preflight more accurate and honest about uncertainty.
- Improve review index inspection samples so they are useful for QA.
- Add explicit index snapshot dates to review preparation and retrieval outputs.
- Make polling hints reflect actual preparation state.
- Add compact workflow help for fresh-context agents.
- Add a transparent corpus-suggestion tool that proposes candidate PMID sets for
  review grounding without synthesizing clinical conclusions.
- Keep public MCP behavior research-use scoped and deterministic.

## Non-Goals

- No backend LLM calls.
- No diagnosis, treatment, triage, patient management, or clinical decision
  support behavior.
- No default publisher scraping, arbitrary PDF extraction, or non-lawful full
  text retrieval.
- No full systematic-review UI or collaboration workflow.
- No short MCP aliases in this sprint unless later measurement proves they reduce
  actual client-visible token cost without duplicate tool-selection overhead.

## Verified Current State

### Metadata

`pubtator.search_literature` can expose authors only when upstream PubTator search
returns them and when `response_mode` allows them. Compact search currently
returns `authors=[]`. There is no dedicated `pubtator.get_publication_metadata`
tool or REST route for citation-quality metadata.

### Source Preflight

`SourcePreflightService.from_pubtator_client()` probes PubTator abstract and PMC
BioC availability, but it does not use NCBI ID conversion by default. This means
preflight can report `expected_coverage="unknown"` or `coverage_reason="no_pmcid"`
even when indexing later resolves usable full text through a different route.

### Inspection Samples

`inspect_review_index` samples passages by section and passage ID. It can return
short headings or low-value sections such as author contributions instead of
representative evidence-bearing text.

### Polling And Snapshots

`index_review_evidence` returns `retry_after_ms=5000` only while queued/running,
which avoids terminal-state stalls, but the value is still fixed. Search,
publication passages, and batch retrieval include `corpus_snapshot_date`;
`index_review_evidence` and `inspect_review_index` do not expose a separate
`index_snapshot_date`.

### Workflow Help

`pubtator.get_server_capabilities` and `pubtator://capabilities` document the
workflow, but the payload is broad. Fresh-context agents would benefit from a
small, workflow-first helper.

## Proposed Public Surface

### `pubtator.get_publication_metadata`

Add a read-only MCP tool and REST route:

```json
{
  "pmids": ["33454820", "39540697"],
  "include_mesh": true,
  "include_citations": true
}
```

Response shape:

```json
{
  "success": true,
  "metadata": [
    {
      "pmid": "33454820",
      "status": "found",
      "title": "Adherence to best practice consensus guidelines for familial Mediterranean fever: a modified Delphi study among paediatric rheumatologists in Turkey.",
      "authors": [
        {"last_name": "Kavrul Kayaalp", "initials": "G"}
      ],
      "journal": "Rheumatology International",
      "year": "2022",
      "pub_date": "2022 Jan",
      "volume": "42",
      "issue": "1",
      "pages": "87-94",
      "doi": "10.1007/s00296-020-04776-1",
      "pmcid": "PMC7811395",
      "publication_types": ["Journal Article"],
      "mesh_headings": [
        {
          "descriptor": "Familial Mediterranean Fever",
          "major_topic": false
        }
      ],
      "citations": {
        "nlm": "Kavrul Kayaalp G, Sozeri B, Sonmez HE. Adherence to best practice consensus guidelines for familial Mediterranean fever: a modified Delphi study among paediatric rheumatologists in Turkey. Rheumatol Int. 2022;42(1):87-94.",
        "vancouver": "Kavrul Kayaalp G, Sozeri B, Sonmez HE. Adherence to best practice consensus guidelines for familial Mediterranean fever: a modified Delphi study among paediatric rheumatologists in Turkey. Rheumatol Int. 2022;42(1):87-94.",
        "bibtex": "@article{pmid33454820,title={Adherence to best practice consensus guidelines for familial Mediterranean fever: a modified Delphi study among paediatric rheumatologists in Turkey},journal={Rheumatology International},year={2022},volume={42},number={1},pages={87-94},doi={10.1007/s00296-020-04776-1}}"
      },
      "source_urls": [
        "https://pubmed.ncbi.nlm.nih.gov/33454820/"
      ]
    }
  ],
  "failed_pmids": [],
  "candidate_pmids": ["33454820", "39540697"],
  "_meta": {
    "next_commands": [
      {
        "tool": "pubtator.preflight_review_sources",
        "arguments": {"pmids": ["33454820", "39540697"]}
      }
    ],
    "source_urls": ["https://www.ncbi.nlm.nih.gov/books/NBK25501/"],
    "unsafe_for_clinical_use": true
  }
}
```

Metadata retrieval should use NCBI ESummary/EFetch and the existing retry helper.
One missing PMID should produce a per-PMID failure record, not fail the whole
batch.

### Search Metadata Enrichment

Keep `pubtator.search_literature` compact by default. Add an optional
`metadata="none" | "basic" | "full"` argument:

- `none`: current compact behavior.
- `basic`: fill authors, journal, year, volume, issue, pages, DOI, PMCID when
  cheap.
- `full`: include publication types, MeSH headings, and citations.

This argument must call the same metadata service used by
`get_publication_metadata`, so citation behavior stays DRY.

### Source Preflight Accuracy

Default source preflight should include NCBI ID conversion for PMID -> PMCID/DOI.
Preflight output should distinguish:

- `full_text_available`: resolver confirms likely full text.
- `abstract_fallback_used`: abstract exists but full text was not confirmed.
- `no_pmcid`: ID conversion found no PMCID.
- `pre_resolution_best_guess`: preflight could not complete enough resolver
  checks to make a final claim.

`coverage_reason="no_pmcid"` should only be used after ID conversion succeeds
and confirms no PMCID. If ID conversion did not run or failed, use a best-guess
reason instead.

### Inspection Sample Selection

Extend `inspect_review_index` with:

- `min_sample_chars: int = 80`
- `sample_section_policy: "evidence_first" | "original_order" = "evidence_first"`

`evidence_first` ranks samples by:

1. passages with `length(text) >= min_sample_chars`,
2. evidence-bearing sections such as abstract, methods, results, discussion,
   conclusion,
3. lower-priority sections last, including author contributions,
   acknowledgments, references, funding, competing interests, abbreviations, and
   short headings,
4. stable passage ID as a deterministic tie-breaker.

If no passage meets `min_sample_chars`, return the best available sample and
include `sample_warning`.

### Snapshot Fields

Add `index_snapshot_date` to:

- `IndexReviewEvidenceResponse`,
- `InspectReviewIndexResponse`,
- `RetrieveReviewContextResponse`,
- `RetrieveReviewContextBatchResponse`,
- `ReviewAuditBundle`.

Meaning:

- `corpus_snapshot_date`: date when a live upstream corpus was queried for a
  response.
- `index_snapshot_date`: date when the review index state represented by the
  response was prepared or inspected.

For now, use the current local date as a conservative snapshot stamp. Future work
can replace this with upstream release metadata if PubTator exposes it.

### State-Aware Polling Hints

Replace fixed `retry_after_ms=5000` logic with a helper:

```text
queued + running == 0 -> null
1-3 active jobs -> 3000
4-10 active jobs -> 5000
>10 active jobs -> 10000
```

The helper should live in a small service or model utility so MCP and REST
responses stay consistent.

### `pubtator.workflow_help`

Add a compact read-only tool that returns only the canonical workflows and small
sample calls:

```json
{
  "success": true,
  "workflows": [
    {
      "name": "ground_review_answer",
      "steps": [
        {"tool": "pubtator.search_literature"},
        {"tool": "pubtator.get_publication_metadata"},
        {"tool": "pubtator.preflight_review_sources"},
        {"tool": "pubtator.index_review_evidence"},
        {"tool": "pubtator.inspect_review_index"},
        {"tool": "pubtator.retrieve_review_context_batch"}
      ]
    }
  ],
  "tips": [
    "Use compact search first.",
    "Use metadata before final citations.",
    "Use dry_run=true before expensive retrieval."
  ]
}
```

This should be smaller than `get_server_capabilities` and aimed at agents that
missed the initial server instructions.

### `pubtator.suggest_corpus`

Add a transparent corpus suggestion tool:

```json
{
  "question": "Turkish child MEFV VUS colchicine FMF",
  "max_pmids": 10,
  "entity_ids": ["@GENE_MEFV"],
  "include_guidelines": true
}
```

Response shape:

```json
{
  "success": true,
  "question": "Turkish child MEFV VUS colchicine FMF",
  "candidate_pmids": ["40234174", "39540697"],
  "candidates": [
    {
      "pmid": "40234174",
      "role": "guideline",
      "rationale": "Guideline/recommendation search hit for FMF management.",
      "metadata": {
        "title": "EULAR/PReS endorsed recommendations for the management of familial Mediterranean fever: 2024 update.",
        "authors": [{"last_name": "Ozen", "initials": "S"}],
        "year": "2025"
      },
      "coverage_hint": {"expected_coverage": "abstract_only"}
    }
  ],
  "role_counts": {
    "guideline": 1,
    "review": 1,
    "cohort": 1,
    "mechanism": 1,
    "treatment_safety": 1
  },
  "_meta": {
    "next_commands": [
      {
        "tool": "pubtator.stage_research_session",
        "arguments": {"pmids": ["40234174", "39540697"]}
      }
    ],
    "unsafe_for_clinical_use": true
  }
}
```

`suggest_corpus` must be deterministic and transparent:

- It may call search, guideline search, related article expansion, metadata, and
  preflight services.
- It must not synthesize clinical conclusions.
- It must expose why each PMID was selected.
- It should prefer a balanced mix over a pure score sort.
- It should return fewer than `max_pmids` when evidence is weak instead of
  padding with poor candidates.

Initial candidate roles:

- `guideline`
- `review`
- `cohort`
- `mechanism`
- `treatment`
- `treatment_safety`
- `variant_interpretation`
- `related`

## Internal Components

### Metadata Models

Create focused models in a new module, for example
`pubtator_link/models/publication_metadata.py`:

- `PublicationAuthor`
- `PublicationMeshHeading`
- `PublicationMetadataRecord`
- `PublicationMetadataResponse`
- `FailedPublicationMetadata`

### Metadata Service

Create `pubtator_link/services/publication_metadata.py`.

Responsibilities:

- call an NCBI metadata client,
- normalize authors and publication details,
- build NLM/Vancouver/BibTeX citation strings,
- preserve failed PMIDs,
- expose a typed batch response.

### NCBI Metadata Client

Extend the NCBI discovery layer or add a small adjacent client module. Keep it
focused:

- ESummary for core metadata,
- EFetch XML only when MeSH headings are requested and ESummary is insufficient,
- retry/backoff via the existing retry helper,
- bounded batch size.

### Corpus Suggestion Service

Create `pubtator_link/services/corpus_suggestion.py`.

Responsibilities:

- run a small set of deterministic search strategies,
- deduplicate by PMID,
- enrich candidates with metadata and coverage hints,
- assign transparent roles and rationales,
- cap output by `max_pmids`,
- produce `_meta.next_commands`.

This service should compose existing services rather than owning HTTP clients
directly.

### Review State Utilities

Add small utilities for:

- polling hint calculation,
- snapshot date stamping,
- sample ranking policy.

Avoid expanding `review_context_service.py` or repository methods into god
modules. SQL-specific sample ranking can live near the repository; pure ranking
logic should be isolated if it is easier to test outside SQL.

## Error Handling

- MCP tools use `run_mcp_tool`.
- Metadata and corpus suggestion return partial success when individual PMIDs
  fail.
- Centralized MCP errors remain sanitized and include recovery hints.
- Source preflight failures should set best-guess coverage reasons rather than
  misleading final reasons.

## Testing Strategy

Use TDD task-by-task.

Required focused tests:

- metadata models validate author, citation, and MeSH shapes,
- metadata service returns found and failed records without fabricating authors,
- REST metadata route validates PMID input and returns typed metadata,
- MCP metadata tool is registered with output schema and research-use notice,
- search metadata enrichment reuses the metadata service and keeps compact
  defaults lean,
- source preflight uses ID conversion before declaring `no_pmcid`,
- source preflight labels failed conversion as best guess,
- inspect samples skip stub passages when longer evidence passages exist,
- inspection response includes warnings when no sample meets `min_sample_chars`,
- index/inspect/retrieve/audit responses include `index_snapshot_date`,
- polling hint helper returns null for terminal status and scales with active
  jobs,
- workflow help returns a compact canonical chain,
- corpus suggestion returns balanced candidates, rationales, coverage hints,
  candidate PMIDs, and next commands,
- batch dry-run schema/tool descriptions mention predicted hit counts,
- MCP public tool inventory remains intentional and excludes destructive public
  operations.

Final verification remains `make ci-local`.

## Documentation Updates

Update:

- `README.md`
- `docs/MCP_CONNECTION_GUIDE.md`
- `docs/development/operations-runbook.md`
- MCP capabilities resource

Documentation should state:

- use `get_publication_metadata` before final citation lists,
- preflight hints are estimates until indexing confirms coverage,
- `index_snapshot_date` and `corpus_snapshot_date` have different meanings,
- `workflow_help` is the compact agent entry point,
- `suggest_corpus` proposes candidates but does not decide clinical relevance.

## Acceptance Criteria

- LLM clients can obtain author-complete Vancouver/NLM/BibTeX metadata for a
  PMID list without fabricating citation fields.
- Source preflight no longer reports `no_pmcid` unless ID conversion confirmed
  that condition.
- `inspect_review_index` samples are evidence-bearing by default.
- Index, inspect, retrieval, and audit outputs expose `index_snapshot_date`.
- Terminal index responses do not include a polling delay.
- `pubtator.workflow_help` is compact and registered.
- `pubtator.suggest_corpus` returns candidate PMIDs with roles, rationales,
  metadata, coverage hints, and handoff commands.
- Existing strong behaviors remain: flat args, stable passage IDs, research-use
  scope, compact defaults, and non-destructive public hosted MCP surface.
