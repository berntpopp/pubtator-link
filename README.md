# pubtator-link

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/berntpopp/pubtator-link/actions/workflows/ci.yml/badge.svg)](https://github.com/berntpopp/pubtator-link/actions/workflows/ci.yml)
[![Conformance](https://github.com/berntpopp/pubtator-link/actions/workflows/conformance.yml/badge.svg)](https://github.com/berntpopp/pubtator-link/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An MCP (Streamable HTTP) server over NCBI's [PubTator3](https://www.ncbi.nlm.nih.gov/research/pubtator3/)
biomedical literature API: PubMed/PMC search, entity and relation annotation, and a
review-scoped retrieval index that returns compact, citable passages instead of raw BioC.

> [!IMPORTANT]
> Research use only. Not clinical decision support. Do not use for diagnosis,
> treatment, triage, or patient management.

## Why

PubTator3 has a good REST API, but it is built for bulk export, not for a model with a
context window. Its unit of exchange is a whole BioC document — one full-text article can
exhaust an LLM's context — and it has no notion of a *corpus* that survives a turn, so an
agent re-fetches and re-reads the same papers on every question.

pubtator-link adds the layer a literature review actually needs: a rate-limit-respecting
client (PubTator3 permits at most 3 requests/second), compact citable passages in place of
raw BioC, and a durable review index keyed by a caller-chosen `review_id` — prepared
passages land in Postgres/pgvector, so evidence can be retrieved, cited by a stable passage
ID, expanded to its neighbours, and audited across sessions. Retrieved article text is
treated as evidence, never as instructions.

## Quick start

The fleet is hosted behind the [genefoundry-router](https://github.com/berntpopp/genefoundry-router),
which owns edge auth; tools surface there as `pubtator_<tool>`:

```bash
claude mcp add --transport http genefoundry https://genefoundry.org/mcp
```

The backend itself (`https://pubtator-link.genefoundry.org/mcp`) is deliberately not a
public origin: it requires the router's service bearer token (see [Security](docs/SECURITY.md)).

To run it locally (Python 3.12+, [uv](https://github.com/astral-sh/uv)):

```bash
make install
cp .env.example .env
make dev                                                     # REST + MCP on :8000
claude mcp add --transport http pubtator-link http://127.0.0.1:8000/mcp
```

No data build is needed — PubTator3 is a live API. The **review-index tools additionally
require PostgreSQL with pgvector**; the Compose stack starts one:

```bash
make docker-up                       # app + pgvector sidecar
make db-migrate                      # PUBTATOR_LINK_DATABASE_URL must be set
```

Without a database the review tools degrade: call `diagnostics`, then fall back to
`get_publication_passages` for the same PMIDs. The default tool profile is `readonly`
(full read surface, no write tools) — see [Configuration](docs/configuration.md).

## Tools

| Tool | Purpose |
|------|---------|
| `workflow_help` | Canonical research workflow for a fresh context |
| `get_server_capabilities` | Supported tools, transports, formats, and limitations |
| `diagnostics` | Subsystem status and recovery commands |
| `search_literature` | PubMed literature search through PubTator3 |
| `search_guidelines` | Guideline, consensus, and systematic-review papers |
| `suggest_corpus` | Compact review-feeding candidate PMID corpus for a question |
| `search_biomedical_entities` | Canonical PubTator entity IDs (gene, disease, chemical, species, variant, cell line) |
| `find_entity_relations` | Literature-derived related entities for a PubTator entity |
| `get_mesh` | MeSH descriptors and candidate PubMed search terms |
| `get_citation` | Candidate PMIDs from a free-text citation |
| `convert_article_ids` | Normalize PMIDs, PMCIDs, and DOIs to candidate PMIDs |
| `find_related_articles` | Similar, cited-by, or reference-linked articles for seed PMIDs |
| `find_related_evidence_candidates` | Full-text-preferred related candidates for one seed PMID |
| `get_publication_citation_graph` | Reference and cited-by neighbours for one publication |
| `build_topic_literature_map` | Bounded topic map across papers, authors, citations, and entities |
| `get_publication_metadata` | Citation-grade metadata for known PMIDs |
| `get_publication_passages` | Compact citable passages for PMIDs, without raw BioC |
| `estimate_publication_context` | Estimate passage count and context size before fetching |
| `get_publication_annotations` | Raw PubTator BioC annotation export for PMIDs |
| `get_pmc_annotations` | Raw full-text BioC annotation export for PMC IDs |
| `get_variant_evidence` | Source-attributed variant records and literature evidence for a gene |
| `get_text_annotation_results` | Results for an asynchronous text-annotation session |
| `preflight_review_sources` | Source coverage and full-text vs abstract-only outlook before indexing |
| `inspect_review_index` | Indexed PMIDs, sections, passage counts, and failures for a `review_id` |
| `get_review_index_summary` | One persisted review index summary, without passage samples |
| `list_review_indexes` | Persisted review indexes with status, counts, and storage size |
| `get_review_context` | Compact citable context from prepared review passages |
| `get_review_context_batch` | Preferred retrieval path: merges several query variants in one call |
| `get_review_passages_by_id` | Exact prepared review passages by stable passage ID |
| `get_neighboring_review_passages` | Prepared passages adjacent to a cited passage, for local context |
| `get_review_audit_trail` | Copy-ready audit block for selected prepared passages |
| `get_evidence_certainty` | One user-supplied evidence-certainty judgment |
| `list_evidence_certainty` | User-supplied evidence-certainty judgments for a review |
| `get_research_session_status` | Staged candidate, coverage, and preparation status |
| `list_research_sessions` | Staged research sessions for a review ID |

That is the default `readonly` surface. The `lean` and `full` profiles add write tools
(indexing, staging, recording, audit-bundle export) and require service auth —
[Security](docs/SECURITY.md) explains why.

Leaf names are unprefixed per [Tool-Naming Standard v1](https://github.com/berntpopp/genefoundry-router/blob/main/docs/TOOL-NAMING-STANDARD-v1.md);
`serverInfo.name` is `pubtator-link` and the canonical gateway namespace token is
`pubtator`, so behind genefoundry-router they surface as `pubtator_<tool>` (e.g.
`pubtator_search_literature`). Standalone MCP clients already namespace them as
`mcp__pubtator-link__<tool>`, so leaf names stay clean to avoid double-prefixing;
[`CHANGELOG.md`](CHANGELOG.md) holds the v2.0.0 migration map from the old `pubtator_`-prefixed
names. Argument shapes, response modes, and MCP resource URIs are in the
[tool catalog](docs/mcp-tool-catalog.md) and the [MCP connection guide](docs/MCP_CONNECTION_GUIDE.md).

## Data & provenance

**Upstream.** The [PubTator3 API](https://www.ncbi.nlm.nih.gov/research/pubtator3-api)
(NCBI), plus NCBI's text-processing API for NER submissions. There is no local bundle and
no ingest step: every call is live, and responses are async-LRU cached.

**Rate limit.** PubTator3 permits at most 3 requests/second. The client ships
`RATE_LIMIT_PER_SECOND=2.5` to stay under that ceiling; do not raise it above 3.

**Provenance.** Prepared review passages are stored in *your own* Postgres, scoped by a
caller-chosen `review_id` — a durable project slug, never PHI, and never an identifier for
patient data. Do not submit identifiable patient data to public instances.

**Citation.** Cite the underlying publications, not this server. Search hits and passages
carry a `recommended_citation` field and a `stable_citation_key`; paste them verbatim
rather than paraphrasing. PubTator3 annotations are produced by NCBI; the abstracts and
full text they annotate remain under their publishers' terms.

## Documentation

- [MCP connection guide](docs/MCP_CONNECTION_GUIDE.md) — clients, the review workflow, response modes, and troubleshooting.
- [Tool catalog](docs/mcp-tool-catalog.md) — generated per-tool schemas and arguments.
- [Configuration](docs/configuration.md) — the `PUBTATOR_LINK_` environment prefix, the tool profiles, and caching.
- [REST API](docs/rest-api.md) — the FastAPI surface: export, search, relations, annotation.
- [Architecture](docs/architecture.md) — package layout, transports, and the review re-RAG subsystem.
- [Deployment](docs/deployment.md) — Docker, the pgvector sidecar, health, and observability.
- [Security](docs/SECURITY.md) — service token, write-surface hardening, and Host/Origin policy.
- [AGENTS.md](AGENTS.md) — engineering conventions for humans and coding agents.

## Contributing

Read [`AGENTS.md`](AGENTS.md) first: it carries the make targets, the file-size budget, and
the testing layout. `make ci-local` is the definition-of-done gate — format, lint, line
budget, README standard, mypy, and tests. Release notes live in [`CHANGELOG.md`](CHANGELOG.md).

## License

[MIT](LICENSE) © Bernt Popp — code only. PubTator3 annotations are an NCBI product and the
literature they annotate stays under its publishers' terms; consult
[NCBI's PubTator3 pages](https://www.ncbi.nlm.nih.gov/research/pubtator3/) before
redistributing retrieved content.
