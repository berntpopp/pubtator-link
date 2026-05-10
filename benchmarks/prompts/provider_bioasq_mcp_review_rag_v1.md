Answer one BioASQ ideal-answer benchmark case using PubTator-Link MCP tools.

Use the PubTator-Link MCP to answer as well as possible from biomedical evidence.

Recommended workflow:
1. Use target_pmids from the case when present.
2. Call pubtator_preflight_review_sources when available to learn whether full text or abstracts are available.
3. Call pubtator_index_review_evidence for those PMIDs with wait_until_ready for this small benchmark case.
4. Call pubtator_inspect_review_index to confirm indexed source coverage.
5. Call pubtator_retrieve_review_context_batch with short query variants and response_mode "quotes".
6. Prefer full-text passages when available; otherwise use abstract passages.
7. Write the answer only from returned passages.

Citation policy:
- Cite only PMIDs or passage IDs returned by MCP tools.
- Every claim should include cited_pmids.
- If the retrieved passages do not support a claim, omit the claim.
- Do not provide clinical advice.

Return JSON only with exactly these keys:
{"case_id":"...","predicted_answer":"...","cited_pmids":[],"retrieved_pmids":[],"source_access":{"PMID":"full_text|abstract_only|metadata_only|missing"},"claims":[{"text":"...","cited_pmids":[]}],"tool_workflow":"preflight_review_sources>index_review_evidence>inspect_review_index>retrieve_review_context_batch","mcp_experience":{"tool_discoverability":1,"context_quality":1,"context_size_control":1,"citation_support":1,"latency":1,"error_recovery":1,"workflow_ergonomics":1,"notes":"..."}}

mcp_experience ratings must be integers from 1 to 10 from your perspective as an LLM consuming this MCP. Do not include markdown.

Case:
{{ case_json }}
