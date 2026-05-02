# Variant Evidence Lookup Design

Date: 2026-05-02

## Purpose

Add a research-scoped variant evidence lookup primitive for clinical-genetics
literature workflows without turning PubTator-Link into a clinical decision
support or variant-classification engine.

The goal is source-attributed retrieval: "what do trusted sources and the
literature say about this variant?" The server must not infer a final medical
classification.

## Goals

- Accept a gene plus HGVS/cDNA/protein/common variant expression.
- Normalize or search variant identifiers where supported.
- Add HPO/Phenotype grounding for clinical-genetics query construction.
- Return source-attributed variant records from public databases.
- Return PubTator/LitVar-style literature evidence for the specific variant.
- Surface uncertainty, conflicts, provenance, and source dates.
- Keep classification labels as quoted/source-attributed data.

## Non-Goals

- No diagnosis, treatment, triage, patient management, or clinical decision
  support.
- No backend ACMG/AMP classification calculation.
- No direct use of proprietary or unverified scraped databases.
- No INFEVERS/INSAID integration until access, licensing, and API stability are
  verified.
- No REVEL score computation unless a lawful, versioned data source is
  explicitly added.

## Current State

Existing useful pieces:

- `search_biomedical_entities` supports `Variant` concept search.
- `search_biomedical_entities` does not currently expose `Phenotype`/HPO as a
  concept.
- `search_literature` can search variant text and PubTator entity IDs.
- Citation metadata and audit bundles now support source-grounded reports.

Gaps:

- No single tool accepts `gene + variant` and coordinates database lookup plus
  literature lookup.
- Variant-specific workflows currently require free-text search strings such as
  "INSAID consensus MEFV".
- There is no structured place to return ClinVar/VCV/RCV identifiers,
  classification labels, review status, conflicts, citations, and literature
  evidence together.

## Public Surface

Add one MCP tool and REST route:

```text
pubtator.lookup_variant_evidence
POST /api/variants/evidence
```

Input:

```json
{
  "gene": "MEFV",
  "variant": "c.2177T>C",
  "protein": "p.Val726Ala",
  "condition": "familial Mediterranean fever",
  "sources": ["clinvar", "pubtator"],
  "max_literature_pmids": 20,
  "include_citations": true
}
```

Only `gene` plus one variant expression is required. `condition` narrows results
but must not be required.

Also expand entity grounding:

```text
search_biomedical_entities(concept="Phenotype")
```

Phenotype results should prefer HPO identifiers when available and should be
usable as `entity_ids` or query expansion inputs for literature search.

Output:

```json
{
  "success": true,
  "query": {
    "gene": "MEFV",
    "variant": "c.2177T>C",
    "condition": "familial Mediterranean fever"
  },
  "normalized_variants": [
    {
      "source": "clinvar",
      "variation_id": "12345",
      "allele_id": "67890",
      "preferred_name": "NM_000243.3(MEFV):c.2177T>C",
      "hgvs": ["NM_000243.3:c.2177T>C", "NP_000234.1:p.Val726Ala"],
      "rsid": "rs..."
    }
  ],
  "source_classifications": [
    {
      "source": "clinvar",
      "classification": "Pathogenic",
      "review_status": "criteria provided, multiple submitters, no conflicts",
      "condition": "Familial Mediterranean fever",
      "variation_id": "12345",
      "last_evaluated": "2025-01-01",
      "url": "https://www.ncbi.nlm.nih.gov/clinvar/variation/12345/"
    }
  ],
  "literature": [
    {
      "pmid": "12345678",
      "title": "...",
      "citation_metadata": {},
      "match_reason": "variant_name_and_gene",
      "coverage_hint": {}
    }
  ],
  "conflicts": [],
  "warnings": [
    "Classifications are source-attributed; PubTator-Link does not compute clinical significance."
  ],
  "source_versions": {
    "clinvar": "live",
    "pubtator3": "live"
  }
}
```

## Source Strategy

### Phase 1: ClinVar + PubTator

Use ClinVar through NCBI E-utilities:

- `esearch(db=clinvar)` for `gene[gene] AND variant text`,
- `esummary(db=clinvar, retmode=json)` for overview records,
- optional `efetch` XML only when summary lacks needed fields.

Use PubTator for literature:

- variant entity search when normalized IDs are available,
- fallback text query: `(<gene>) AND (<variant aliases>)`,
- attach metadata with existing `PublicationMetadataService`.

Add HPO/Phenotype support in the same phase only if it can reuse existing
entity-search infrastructure or a small deterministic HPO lookup. If HPO needs a
new dependency or downloaded ontology data, split it into a separate task inside
the same implementation plan.

### Phase 2: Optional Domain Sources

Evaluate separately:

- ClinGen Evidence Repository APIs,
- LitVar/tmVar identifier normalization,
- INFEVERS/INSAID availability and license,
- REVEL source licensing/versioning.

Do not ship labels from sources whose access terms are unclear.

## Safety And Wording

The tool should return source-attributed labels only. Use one global
research-use notice in server instructions/capabilities. The tool-specific
description should be concise:

```text
Look up source-attributed variant records and literature evidence for a gene and
variant. Does not compute clinical classification.
```

## Error Handling

- Ambiguous variant: return multiple normalized candidates with `needs_disambiguation=true`.
- No database record: return empty `source_classifications` and suggested
  literature queries.
- Upstream unavailable: partial success if literature or metadata still works.
- Conflicting classifications: return `conflicts` explicitly; do not reconcile.

## Testing

Required tests:

- input normalization for cDNA/protein/common variant strings,
- ClinVar query construction,
- ClinVar summary parsing,
- source-attributed classification output,
- partial success when ClinVar fails but PubTator literature succeeds,
- no computed classification field,
- MCP/REST schema tests.

## References

- ClinVar API access via E-utilities:
  https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/
- ClinVar search fields and classification filters:
  https://www.ncbi.nlm.nih.gov/clinvar/docs/help/
- ClinVar file/API primer:
  https://www.ncbi.nlm.nih.gov/clinvar/docs/ftp_primer/
