# Changelog

## Unreleased

- Disabled cache management endpoints by default and made cache clear semantics
  honest: full clears report actual entries cleared, while scoped pattern clears
  now return HTTP 400.
- Removed the unused broken `PublicationService.batch_export_publications()`
  helper.
- Added PubTator export retry metadata sidecars for review preparation audit
  rows without shared mutable client state.
- Corrected MCP review write annotations so append/create tools are marked
  non-idempotent and deduplicated indexing tools remain idempotent.
- Changed review preparation workers to atomically claim queued jobs in a short
  database transaction before running upstream fetch, parser, and embedding work.
- Documented MCP search metadata mapping for flat `publication_types`, `year_min`, and
  `year_max` arguments.
- Clarified that `source_fair` and `scarcity_first` are opt-in review retrieval budget
  strategies while `query_fair` remains the default.
- Documented stable citation keys and maps for durable downstream references.
- Added lifecycle guidance for repeated `index_review_evidence` calls and prompt-injection
  handling for retrieved article text.
