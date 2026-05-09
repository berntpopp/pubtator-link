# MEFV Claude MCP Benchmark

Date: 2026-05-02

## Purpose

The experiment ran Claude Code 10 times against the PubTator-Link MCP using a
strict clinical-genetics prompt. The clinical scenario was a child from Turkey
with recurrent fever and a weak MEFV VUS, with a request for guideline-grounded
colchicine framing suitable for a clinical genetics report.

Each Claude session had two turns:

1. Generate a PubTator-Link-grounded clinical report paragraph with source list
   and audit trail.
2. Evaluate PubTator-Link as an MCP consumer on speed, context management,
   discoverability, argument clarity, retrieval quality, provenance,
   diagnostics, workflow fit, limits, and improvement opportunities.

Raw timestamped outputs, Claude debug logs, and Docker logs are ignored by git.
This document records the curated result.

## Run Summary

All 10 Claude Code runs completed with exit status 0 for both turns. One run
(`run_04`) was a false success: Claude returned success JSON with an empty
clinical `result`, so only 9/10 clinical outputs were usable.

| Run | Clinical | Eval | Clinical output |
| --- | ---: | ---: | --- |
| run_01 | 236s | 60s | usable |
| run_02 | 458s | 52s | usable |
| run_03 | 240s | 65s | usable |
| run_04 | 293s | 64s | empty result despite success |
| run_05 | 249s | 59s | usable |
| run_06 | 251s | 91s | usable |
| run_07 | 228s | 53s | usable |
| run_08 | 185s | 51s | usable |
| run_09 | 216s | 49s | usable |
| run_10 | 291s | 67s | usable |

Average runtime:

- Clinical generation: 264.7 seconds.
- MCP self-evaluation: 61.1 seconds.
- Total sequential benchmark time: 54.3 minutes.

## Scientific Assessment

Stable synthesis across usable outputs:

- A single weak or VUS MEFV finding is not sufficient by itself to establish
  familial Mediterranean fever (FMF).
- FMF diagnosis in this scenario should be phenotype-led, with clinical criteria
  and inflammatory phenotype carrying more weight than the isolated VUS.
- VUS-only or single-heterozygous VUS cohorts, especially E148Q-heavy cohorts,
  were repeatedly described as mild-to-moderate and often comparable to
  single-heterozygous pathogenic carriers.
- Colchicine was consistently described as first-line or mainstay therapy for
  clinically diagnosed FMF, not as a genotype-only recommendation for an
  isolated weak VUS.
- The most conservative stable answer was: PubTator-Link did not retrieve a
  guideline passage explicitly endorsing colchicine solely because of an
  isolated weak MEFV VUS without a clinical FMF phenotype.

Risky variability:

- Some runs moved from conservative report language into stronger treatment
  framing such as "typically managed with a colchicine trial" or "support
  framing by response to colchicine." These statements were sometimes marked as
  inferred, but that distinction may be too subtle for a clinical report.
- Some outputs cited secondary summaries for EULAR dosing or recommendations
  when the primary EULAR paper was not retrieved at passage level.
- Run 8 over-focused on updated EULAR/PReS systematic-review evidence and
  colchicine safety, with weaker direct connection to the Turkish child / weak
  VUS scenario.
- Run 4 exposed a critical harness/model failure because a successful process
  status did not imply a non-empty answer.

## Overlap And Variability

Recurring PMIDs:

- PMID 39540697: pediatric/Turkish FMF review.
- PMID 33454820: Turkish pediatric Delphi / EULAR-aligned consensus.
- PMID 33726481: Central Anatolian VUS phenotype cohort.
- PMID 40067091: pediatric Turkish VUS-only cohort.
- PMID 37752496: pediatric treat-to-target / AID-NET.
- PMID 39882210, PMID 41313543, and PMID 35382375: criteria, dosing, or PFAPA
  overlap papers that appeared in several runs.
- PMID 26802180 and PMID 40234174 surfaced inconsistently as guideline metadata
  or abstracts, not reliably as passage-level guideline text.

Variability was high enough that a single run should not be treated as stable
scientific output. The best common synthesis is conservative and genotype
limited; weaker outputs infer more than they should from treatment cohorts.

## MCP Usability Findings

Claude's self-rated overall MCP scores ranged from 7.5/10 to 8.6/10, centered
around approximately 8/10.

Repeated strengths:

- Citation and provenance support: usually 9-10/10.
- Retrieval quality: usually 8-9/10.
- Workflow fit for literature review: usually 9/10.
- Review-scoped indexing and passage-level audit trails were repeatedly useful.

Repeated weaknesses:

- Argument clarity: often 5-6/10.
- Discoverability: often 5-7/10.
- Limits and failure modes: often 6-7/10.
- Models complained about list-shaped arguments such as `pmids` and `queries`,
  inconsistent retrieval names (`query`, `question`, `queries`), case-sensitive
  enums, deferred tool discovery, and canonical guideline retrieval.

## Debug And Docker Log Notes

Claude debug logs showed streaming stalls or slow-first-byte warnings in every
run, usually 1-3 events per run. These appear mostly related to model/API
latency rather than PubTator-Link tool failure.

Docker logs were useful but noisy. Broad four-hour Docker logs contained stale
history from earlier unrelated experiments, including CDH1/PubTator 400 errors.
Future analysis should diff per-run `docker_before.log` and `docker_after.log`
or use timestamp windows before attributing server errors to a specific run.

## Improvement Plan

P0:

- Fail a benchmark run if `clinical_output.json.result` is empty.
- Make the final judge step read from stdin or a file path instead of passing a
  large evidence bundle as a command-line argument.
- Add per-run Docker log deltas or timestamp filtering so stale server errors
  are not attributed to the current run.

P1:

- Add tolerant list parsing or alternate scalar fields such as `pmids_csv`,
  `queries_csv`, and `curated_urls_csv`.
- Unify retrieval argument naming across single and batch tools.
- Improve validation errors with concrete examples and "looks like JSON string"
  hints.
- Add and document `must_include_pmids` or `prioritize_pmids` for relevant
  retrieval/index flows.
- Add or better document a compact `compose_review` / `review_quickstart` flow
  for short clinical report tasks.

P2:

- Improve canonical guideline ranking and guideline anchor-paper discovery.
- Add NLM/Vancouver citation strings directly to passage retrieval responses.
- Improve duplicate-passage substitution in batch retrieval.
- Add latency fields and token estimates to MCP responses.
- Improve `coverage_hint` calibration against actual indexed coverage.

## Next Benchmark Changes

- Run at least three prompt variants: conservative report-only,
  guideline-focused, and adversarial "make a recommendation".
- Add automatic checks for empty outputs, sentence count, PMID count,
  source-list presence, audit-trail presence, and unsupported-claim markers.
- Add a reference-answer rubric that penalizes genotype-only colchicine
  recommendations.
- Diff per-run PMIDs and compute PMID overlap/Jaccard similarity automatically.
- Store model, cost, and token usage in the summary table.
