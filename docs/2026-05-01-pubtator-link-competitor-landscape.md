# PubTator-Link MCP Competitor Landscape

Date: 2026-05-01

## Executive Summary

PubTator-Link sits between two crowded markets: lightweight MCP wrappers around
PubMed/PubTator APIs, and mature systematic-review products. Direct MCP
competitors are improving quickly, but most optimize for search, metadata,
citation formatting, or broad biomedical source coverage. PubTator-Link's current
strongest differentiation is narrower and more defensible: review-scoped,
citable, compact evidence retrieval over PubTator/PubMed/PMC-derived passages.

The strongest product thesis is openness. PubTator-Link can be the open,
inspectable biomedical evidence MCP: open code after specification hardening,
open-source-first evidence sources, deterministic retrieval artifacts, and
institution-controlled deployment. In contrast with closed clinical AI products,
the goal is not opaque answer generation; it is evidence preparation, retrieval,
and citation in a form humans and agents can inspect.

There is also a third adjacent market: clinical AI search and decision-support
products such as OpenEvidence. Those products compete for the user expectation
that a medical AI assistant should synthesize current evidence quickly. They are
not direct MCP competitors, and PubTator-Link should not copy their point-of-care
clinical decision-support positioning. PubTator-Link's safer and more defensible
path is a private or institutional research MCP that gives users evidence
retrieval, provenance, citations, and review audit trails inside their chosen
LLM environment.

The best roadmap is not to imitate full systematic-review platforms. PubTator-Link
should become the evidence-grounding layer that those workflows and LLM agents
need: lawful full-text coverage discovery, transparent source diagnostics,
passage-level addressability, typed MCP schemas, retry/backoff, and audit metadata
aligned with PRISMA/GRADE-style review practice.

## PubTator-Link Baseline

PubTator-Link currently exposes a curated FastAPI and MCP surface for
PubTator3-backed biomedical literature search, annotation export, entity lookup,
entity relations, compact publication passages, review evidence indexing,
review-index inspection, and compact or diagnostic review-context retrieval.
The local capability review describes its core workflow as
`search -> index -> inspect -> retrieve`, with stable citation keys, compact
passage packing, per-query diagnostics, and source-aware retrieval modes.

Core local differentiators:

- Open-code and open-source-first positioning, with source behavior that can be
  inspected, tested, and self-hosted.
- PubTator-native entity and relation grounding rather than plain PubMed keyword
  search only.
- Review-scoped evidence preparation and retrieval instead of one-off article
  fetches.
- Compact passage budgets and dropped-passage diagnostics for LLM context control.
- Deterministic passage IDs and citation keys for auditability.
- Explicit research-use scope in the MCP descriptions.

Main local gaps from the capability review:

- Speed needs more work for research-session workflows where candidate abstracts
  and likely full texts should be staged before the LLM explicitly asks for each
  one.
- Coverage is discovered too late, after indexing.
- Full-text fallback should use lawful APIs before any curated user-supplied URL.
- Retry/backoff and `Retry-After` handling are missing.
- Batch retrieval and preparation have parallelism opportunities.
- Passage-level expansion by exact ID is not exposed.
- Review index lifecycle and typed MCP output models are not yet mature.

## Direct MCP Competitors

| Project | Category | Strengths | Weaknesses Versus PubTator-Link | Differentiation Opportunity |
| --- | --- | --- | --- | --- |
| [BioMCP](https://github.com/genomoncology/biomcp) | Broad biomedical MCP | Very broad source graph: article search uses PubMed, PubTator3, Europe PMC, PMC OA, NCBI ID Converter, and optional Semantic Scholar; also spans genes, variants, trials, drugs, pathways, proteins, disease, adverse events, PGx, and GWAS. | Breadth dilutes the specialized review-corpus problem. It is positioned as "one binary, one grammar" across biomedical sources, not as an audit-grade passage retrieval layer. | Position PubTator-Link as the deep evidence packer for PubTator/PubMed/PMC articles that BioMCP-like systems could call when they need citable review context. |
| [cyanheads/pubmed-mcp-server](https://github.com/cyanheads/pubmed-mcp-server) | PubMed MCP | Strong PubMed implementation with nine tools: search, article metadata, PMC full text with optional Unpaywall fallback, citation formatting, related/citing/reference lookups, spell check, MeSH lookup, citation matching, ID conversion, hosted HTTP option, retries, and storage/auth hooks. | It is PubMed/NCBI-centered rather than PubTator entity/relation-centered. It fetches full text but does not appear to maintain a review-scoped passage index with stable citation keys and compact multi-query retrieval. | Add the missing operational polish that cyanheads already advertises: retries, explicit full-text unavailable reasons, hosted-friendly auth, and ID conversion. Keep the review-corpus layer as the differentiator. |
| [JackKuo666/PubTator-MCP-Server](https://github.com/JackKuo666/PubTator-MCP-Server) | Direct PubTator MCP | Lightweight PubTator3 MCP exposing annotation export, entity ID lookup, relationship mining, literature search, and batch processing; supports PubTator/BioC formats and full-text flag. | Similar source API surface, but appears closer to a raw PubTator wrapper. No obvious review index, citable passage budget, diagnostics, or audit-focused retrieval workflow. | PubTator-Link should emphasize "not just an API wrapper": review preparation, source coverage, passage retrieval, and reproducible context packs. |
| [openpharma-org/pubmed-mcp](https://github.com/openpharma-org/pubmed-mcp) | Simple PubMed MCP | Simple unified `pubmed_articles` tool with keyword search, advanced search, metadata retrieval, and PDF attempt through PMC. | Very small surface and limited repository maturity. Single-tool method multiplexing is less LLM-friendly than focused flat tools. No entity annotations, review index, or retrieval diagnostics. | Keep flat top-level MCP tools and typed schemas; avoid method-multiplexed tools except where unavoidable. |
| [chrismannina/pubmed-mcp](https://github.com/chrismannina/pubmed-mcp) | PubMed search/management MCP | Advanced PubMed search, article details, citation export, author search, related articles, MeSH search, journal analysis, trends, comparison, caching, and rate limiting. | Strong literature-management features but not PubTator annotation or review-passage retrieval focused. Requires API key/email setup. | Add selective citation export/import affordances later, but prioritize evidence traceability over bibliographic convenience. |
| [gradusnikov/pubmed-search-mcp-server](https://github.com/gradusnikov/pubmed-search-mcp-server) and [JackKuo666/PubMed-MCP-Server](https://github.com/JackKuo666/PubMed-MCP-Server) | Lightweight PubMed MCPs | Easy search and metadata retrieval; some PDF/full-text attempts and prompts. | Mostly commodity PubMed wrappers; less differentiated and less evidence-audit oriented. | PubTator-Link should not compete on being the simplest PubMed MCP. It should compete on reliability, evidence context quality, and scientific traceability. |

### Direct MCP Takeaways

Direct competitors prove that PubMed search, metadata fetch, citation formatting,
MeSH lookup, related-article lookup, ID conversion, and PMC/Unpaywall full-text
fallback are now expected table stakes for biomedical MCPs. PubTator-Link's
distinctive wedge is the review-scoped retrieval layer: source coverage inspection,
compact citable context, passage IDs, and query diagnostics.

Roadmap implication: close the obvious MCP parity gaps only where they support
review grounding. The highest-priority parity items are PMC ID conversion,
coverage preflight, structured unavailable reasons, retries/backoff, and
passage-level expansion. Citation formatting, journal analytics, and trend charts
are useful but lower leverage.

## Biomedical Literature and Search APIs

| Source/API | Strengths | Weaknesses / Limits | PubTator-Link Implication |
| --- | --- | --- | --- |
| [PubTator3](https://academic.oup.com/nar/article/52/W1/W540/7640526) | Native biomedical entity and relation layer over PubMed/PMC. The NAR paper reports more than one billion entity/relation annotations across about 36 million PubMed abstracts and 6 million PMC OA full-text articles, updated weekly. API supports keyword, entity, relation search, and BioC/XML/JSON/tabular exports. | Coverage is bounded by PubTator's indexed abstracts/full texts and export behavior. It is powerful but raw API responses are not automatically shaped for LLM context budgets or systematic-review audit trails. | Keep PubTator3 as the primary semantic differentiator. Build better preparation, coverage explanation, and compact retrieval around it. |
| [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/home/develop/api/) | Official PubMed/PMC/Gene/etc. Entrez API suite for search, link, and retrieval operations. Commodity baseline for PubMed MCPs. | Returns metadata/search results, not semantic PubTator annotations or review-ready evidence packs. Requires careful rate-limit etiquette. | Use as complement for ID conversion, metadata, related articles, query translation, MeSH, and fallback diagnostics rather than replacing PubTator search. |
| [BioC-PMC](https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/BioC-PMC/) | PMC Open Access and Author Manuscript articles in BioC XML/JSON, available by PMID or PMCID; designed for text mining and retrieval research. | Not every PMC article is available in these collections. Requires explicit coverage handling. | Add as preferred lawful full-text fallback after PubTator full BioC, with precise `coverage_reason`. |
| [PMC OAI-PMH](https://pmc.ncbi.nlm.nih.gov/tools/oai/) | Metadata for PMC and full text for articles with reuse rights; supports JATS XML and includes license/reuse constraints. | Full text is limited to reusable articles; ListRecords pagination changed in 2025 and returns small batches. | Use for license-aware fallback and record machine-readable license URLs where available. |
| [Europe PMC APIs](https://pmc.ncbi.nlm.nih.gov/articles/PMC4383902/) | REST API for search, metadata, full text, figures, and supplementary files for open-access full-text articles; can expose content outside strict NCBI PubMed workflows. | Some full text is searchable but not redistributable; content and license handling must be explicit. | Optional fallback/source expansion with rate limiting and license labels. |
| [Semantic Scholar API](https://www.semanticscholar.org/product/api) | Strong citation graph, recommendations, embeddings, abstracts, PDF URLs, and summaries. | Not biomedical-specific and not an authoritative PubMed/PubTator source. API-key/rate considerations apply. | Useful for citation expansion and related-paper discovery, not as the primary evidence text source. |
| [OpenAlex Works API](https://docs.openalex.org/api-entities/works) | Very broad scholarly graph over hundreds of millions of works with filtering, sorting, grouping, citation links, and open metadata. | Metadata completeness/cleanliness varies; not biomedical passage or full-text focused. | Useful for discovery breadth and citation-network context; not a substitute for PubMed/PubTator evidence passages. |
| [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | Public DOI metadata API with works, journals, funders, licenses, ORCID/ROR, abstracts, and post-publication update metadata. | Publisher-deposited metadata varies; not a biomedical full-text/evidence retrieval API. | Use for DOI enrichment, license metadata, correction/retraction signals, and citation repair. |
| [CORE API](https://files.core.ac.uk/services/api) | Aggregates open-access metadata and full text from many repositories. | General scholarly corpus; not PubMed/PubTator semantic annotation. API access terms and coverage need verification. | Possible late fallback for open-access full text, after more biomedical-specific sources. |

### API Takeaways

The upstream API landscape favors a resolver cascade, not a single source. The
best PubTator-Link path is:

1. PubTator full BioC export.
2. PubTator abstract export when full text is unavailable.
3. PMC ID Converter plus BioC-PMC.
4. PMC OAI-PMH JATS for license-compatible full text.
5. Europe PMC open-access full text where enabled.
6. Metadata-only enrichment from NCBI, Crossref, Semantic Scholar, and OpenAlex.

Roadmap implication: source attempts should become first-class output data:
`attempt_count`, `source`, `status_code`, `retry_after`, `coverage_reason`,
`license`, `pmcid`, `doi`, `fallback_available`, and `terminal_reason`.

## Full-Text, PubMed, and PMC Tooling

Full-text access is the biggest usability battleground. Direct PubMed MCPs are
already advertising PMC full-text retrieval, Unpaywall fallback, PDF extraction,
and explicit unavailable reasons. PubTator-Link should match the transparent parts
without making hosted instances scrape publisher pages by default.

Recommended posture:

- Prefer structured, lawful text APIs: PubTator BioC, BioC-PMC, PMC OAI-PMH JATS,
  and Europe PMC OA XML.
- Expose preflight coverage before indexing so users know whether a candidate PMID
  is likely full text, abstract only, metadata only, or blocked by reuse limits.
- Avoid default publisher-page/PDF scraping in public hosted MCP deployments.
- Allow curated user-provided URLs only as explicit inputs with provenance labels.
- Store enough extraction metadata to support audit and reproducibility.

Differentiation opportunity: competitors often say "fetch full text" but leave
retrieval quality opaque. PubTator-Link can win by making unavailable reasons and
source coverage visible before the user spends an indexing call.

## Systematic-Review Platforms

| Platform | Strengths | Weaknesses / Non-Goals for PubTator-Link | PubTator-Link Opportunity |
| --- | --- | --- | --- |
| [Elicit Systematic Reviews](https://support.elicit.com/en/articles/7927169) | End-to-end AI workflow: protocol setup, search, title/abstract screening, optional full-text screening, extraction, and report generation. Elicit claims up to 80% time savings. | SaaS product with its own UI and automation opinions. Not an MCP-native evidence grounding service. | Borrow workflow concepts: protocol fields, screening criteria, extraction columns, and report provenance. Do not try to clone the UI. |
| [Rayyan](https://systematicreviewsjournal.biomedcentral.com/articles/10.1186/s13643-016-0384-4) | Widely used web/mobile screening tool with collaboration and semi-automated title/abstract screening. Newer help docs describe AI reviewer/analyzer criteria-driven screening. | Screening-centric; historically weaker on automated full-text extraction, risk of bias, and RevMan integration. | Export/import compatibility and audit metadata could let PubTator-Link feed evidence packs into Rayyan-like workflows. |
| [Covidence](https://www.covidence.org/) | Mature systematic-review management SaaS for collaboration, screening, extraction, and broad review-team workflows; claims large systematic-review community and organization support. | Closed workflow platform, not an agent tool or biomedical API. | PubTator-Link should complement rather than compete: generate traceable evidence context that can support human screening/extraction decisions. |
| [DistillerSR](https://www.distillersr.com/products/distillersr-systematic-review-software/) | Enterprise evidence platform with AI screening, extraction, audit logs, configurable workflows, integrations, full-text retrieval, PRISMA reporting, and regulatory positioning. | Enterprise SaaS scope is far beyond PubTator-Link. | Treat as the auditability benchmark: every automated evidence step should be traceable, reproducible, and exportable. |
| [ASReview LAB](https://asreview.readthedocs.io/en/latest/lab/about.html) | Open-source active-learning screening; documentation cites up to 95% screening-time reduction and supports project export/import. | Focused on screening records, not full-text passage retrieval or PubTator annotations. | Add export formats that make PubTator-Link evidence usable by active-learning screeners. |
| [Cochrane RevMan](https://revman.cochrane.org/info/features) | Review production and meta-analysis with study-data import, collaboration, templates, forest plots, and GRADEpro integration for Cochrane reviews. | Downstream synthesis authoring tool, not discovery or passage retrieval. | Roadmap should support RevMan-adjacent structured exports: study data, outcome evidence, risk-of-bias support, and citation maps. |
| [Epistemonikos API](https://api.epistemonikos.org/) | Evidence-based health-care database with systematic-review and primary-study classification, API filters, and living-review/living-guideline orientation. | Curated evidence database, not an MCP evidence preparation layer. | Use as a discovery/enrichment source for systematic reviews and prior-review awareness. |

### Systematic-Review Takeaways

Systematic-review competitors win on workflow management, collaboration,
screening, extraction, and reporting. PubTator-Link should not become a clone of
Covidence or DistillerSR. It should instead supply an agent-facing evidence layer
that those workflows lack: structured biomedical annotations, lawful full-text
coverage, exact passage retrieval, and reproducible context packs.

Roadmap implication: add review-audit metadata before adding broad workflow UI:
protocol fields, search strings, source attempts, inclusion/exclusion support
passages, extraction support passages, risk-of-bias evidence snippets, and
PRISMA/GRADE export hints. The [PRISMA 2020](https://www.prisma-statement.org/prisma-2020)
checklist and flow-diagram framing should guide audit fields, not force the
server to become a complete systematic-review manager.

## Clinical AI Search and OpenEvidence

OpenEvidence is an adjacent strategic competitor rather than a direct MCP
competitor. Its official site describes it as a leading medical information
platform that organizes medical knowledge for physicians, medical researchers,
and healthcare professionals, with content agreements involving JAMA and The New
England Journal of Medicine. OpenEvidence announcements position the product as a
clinical decision-support and medical search platform for verified U.S.
clinicians, with DeepConsult agents that cross-reference large numbers of
peer-reviewed studies and return evidence-based syntheses. Cochrane announced a
2026 Wiley/OpenEvidence partnership licensing Cochrane evidence and Wiley medical
content into OpenEvidence for users including more than 40% of U.S. physicians.

OpenEvidence's strengths:

- Clear user promise: fast evidence synthesis for clinicians.
- Strong content partnerships: NEJM, JAMA/JAMA Network, Cochrane/Wiley, and
  specialty medical content partnerships.
- Workflow ambition beyond search: point-of-care answers, follow-up suggestions,
  clinical documentation context, and deeper research reports.
- Strong adoption narrative among U.S. clinicians.
- Product language focused on clinician workflows rather than developer APIs.

OpenEvidence's weaknesses or non-goals for PubTator-Link:

- It is a closed clinical AI product, not an open MCP server or inspectable
  evidence-preparation component.
- Public positioning is point-of-care clinical decision support, which raises a
  higher regulatory, validation, and liability bar than research literature
  grounding.
- It is U.S.-clinician-centered and not designed as a local/private institutional
  MCP that users can connect to their own chat or code LLM.
- It does not give PubTator-Link-style control over source attempts, passage
  packing, review indexes, deterministic passage IDs, or local evidence audit
  metadata.

PubTator-Link opportunity:

- Lead with openness: open code, open-source-first evidence, deterministic
  evidence artifacts, and inspectable retrieval behavior.
- Offer an **institution-controlled evidence retrieval layer** rather than a
  hosted clinical answer engine.
- Let universities, hospitals, labs, and review teams connect their preferred
  private or institutional LLM to PubTator/PubMed/PMC evidence without sending
  review state through a separate clinical AI SaaS product.
- Keep backend behavior deterministic: retrieval, preparation, annotation,
  passage packing, and provenance rather than diagnosis, treatment selection, or
  patient-specific clinical recommendations.
- Make outputs audit-friendly enough for institutional governance: source URLs,
  source attempts, coverage reasons, passage IDs, citation maps, retrieval
  parameters, and explicit limitations.

### Regulatory Positioning

- PubTator-Link is research-use biomedical literature infrastructure.
- It is a retrieval and evidence-preparation MCP, not a clinical decision-support
  product.
- It does not provide diagnosis, treatment, triage, patient management, or
  patient-specific clinical recommendations.
- Private or institutional deployment is a data-control and governance advantage,
  with clearer boundaries for security, audit, and data-retention policy.
- If an institution uses PubTator-Link plus an LLM in a clinical workflow, the
  institution and implementer must classify that use case and meet applicable
  AI Act, MDR/IVDR, GDPR, medical device, procurement, security, and audit
  obligations.

The EU public-health guidance notes that high-risk AI systems, including
AI-based software intended for medical purposes, must meet requirements such as
risk mitigation, high-quality data, clear user information, and human oversight.
This supports PubTator-Link's roadmap: source traceability, human-reviewable
evidence packs, explicit limitations, and audit metadata are not optional polish;
they are the core reason an institutional MCP evidence layer can be governed.

## Competitive Positioning

### What PubTator-Link Should Own

- Agent-facing biomedical evidence grounding.
- PubTator entity/relation-aware search and retrieval.
- Review-scoped passage indexes with compact citable outputs.
- Source coverage transparency and lawful full-text fallback.
- Deterministic citation keys and passage IDs.
- Research-use scoped hosted MCP behavior.
- Diagnostics that help LLMs recover from zero-result and abstract-only cases.
- Private or institution-hosted evidence retrieval for users who want their own
  LLM client, data boundary, and governance controls.
- Research-session staging that prepares likely abstracts and full text before
  the LLM asks for every PMID one by one.

### What PubTator-Link Should Avoid Owning

- General-purpose scholarly graph search at OpenAlex/Semantic Scholar scale.
- Bibliographic reference-manager replacement features.
- Full systematic-review SaaS workflow management.
- Default publisher scraping/PDF extraction in public hosted deployments.
- Clinical decision support, diagnosis, treatment, or triage claims.

## Differentiation Opportunities

1. **Coverage-first evidence preparation**
   Add PMID/PMCID preflight before indexing. Return expected coverage, fallback
   source candidates, license/reuse status, and `coverage_reason`.

2. **Transparent resolver cascade**
   Implement PubTator full BioC, PubTator abstract, PMC ID Converter, BioC-PMC,
   PMC OAI-PMH, Europe PMC OA, and metadata-only fallbacks with source-attempt
   diagnostics.

3. **Passage-level addressability**
   Add tools to fetch exact passages by ID, expand a passage, and retrieve
   neighboring passages without new network calls.

4. **MCP usability parity**
   Add typed output models, structured unavailable reasons, retry/backoff,
   `Retry-After` handling, and bounded async parallelism.

5. **Review audit exports**
   Emit review-ready metadata: search query, indexed PMIDs, source coverage,
   excluded sources, passage citations, decision-support passage IDs, and
   PRISMA-style counts.

6. **Interoperability rather than UI competition**
   Export CSV/JSONL/RIS/BibTeX or structured JSON that can feed Rayyan,
   ASReview, Covidence, RevMan, and custom LLM review agents.

7. **Institutional MCP deployment**
   Package the server for local, VPC, hospital, university, and lab deployments
   with authentication, audit logs, data-retention controls, no clinical-use
   default, and clear compliance documentation. The value proposition is data
   control and evidence transparency, not regulatory avoidance.

8. **Research-session prefetch and staging**
   After a literature search or related-article expansion, stage candidate
   abstracts immediately and preflight likely full-text availability in the
   background. Use bounded concurrency, source-rate budgets, cache metadata, and
   explicit session manifests so the LLM can later retrieve passages quickly
   without hiding what was fetched, skipped, or unavailable.

## Recommended Roadmap Implications

### P0: Evidence Reliability and Transparency

- Add source coverage preflight.
- Add lawful full-text resolver cascade.
- Add retry/backoff with `Retry-After`.
- Add structured source-attempt diagnostics.
- Add typed MCP response models for review tools.
- Add audit-trail persistence for source attempts, retrieval parameters, passage
  selections, dropped-passage reasons, and citation maps.

Why: these close the most important gap versus sophisticated PubMed MCPs while
strengthening PubTator-Link's actual differentiator.

### P0.5: Speed and Session Staging

- Add a research-session abstraction that groups searches, candidate PMIDs,
  staged abstracts, coverage preflight results, and prepared full-text passages.
- Prefetch abstracts for top search results immediately after search.
- Preflight PMCID/DOI/full-text availability for candidate PMIDs in batches.
- Prepare likely full-text sources opportunistically with bounded async
  concurrency and strict per-source rate limits.
- Cache source-attempt metadata separately from passage text so future calls can
  explain prior decisions cheaply.
- Surface staging status to MCP clients: `queued`, `fetching`, `abstract_ready`,
  `full_text_ready`, `abstract_only`, `metadata_only`, `failed`, and `skipped`.

Why: OpenEvidence-like user experience depends on speed, but PubTator-Link should
achieve it transparently. Intelligent staging can make later review retrieval
fast without becoming opaque.

### P1: Retrieval Usability

- Add exact passage lookup, passage expansion, and neighboring-passage tools.
- Add bounded parallelism to batch retrieval and evidence preparation.
- Add review index inventory and summary tools.

Why: LLM agents need cheap follow-up retrieval after compact context, and users
need to know what is already indexed.

### P2: Review-Audit Layer

- Add protocol/search metadata capture.
- Add PRISMA-style source counts and export.
- Add extraction-support and risk-of-bias-support passage references.
- Add compatibility exports for screening/review tools.

Why: this moves PubTator-Link toward systematic-review rigor without becoming a
full systematic-review platform.

### P3: Discovery Enrichment

- Add optional Semantic Scholar/OpenAlex/Crossref enrichment for citation graph,
  related works, corrections/retractions, DOI/license metadata, and prior-review
  discovery.
- Add optional Europe PMC/CORE expansion where licensing and rate limits are
  clear.

Why: broad discovery is useful, but only after the core evidence-preparation
contract is reliable.

### P4: Institutional and Governance Readiness

- Add deployment guidance for private/institutional MCP use.
- Add authentication and reverse-proxy reference patterns.
- Add audit-log and retention recommendations.
- Add explicit clinical-use boundary documentation.
- Add compliance-mapping notes for research use, literature review, and
  non-patient-specific evidence synthesis.
- Add a warning that clinical decision-support deployments require independent
  regulatory classification and institutional approval.

Why: OpenEvidence proves demand for medical AI evidence synthesis, but
PubTator-Link's differentiator is deployable, inspectable evidence
infrastructure under user or institutional control.

## Bottom Line

The market already has enough PubMed MCP wrappers, and clinical AI search
products such as OpenEvidence already own the closed point-of-care answer-engine
narrative. PubTator-Link should not win by being another metadata fetcher or by
claiming clinical decision support. It should win by being the agent-native,
PubTator-aware evidence preparation and retrieval layer: compact, citable,
source-transparent, lawful, review-auditable, open-code, open-source-first, and
deployable inside private or institutional LLM workflows. Speed should come from
transparent prefetching and staging, not hidden synthesis.
