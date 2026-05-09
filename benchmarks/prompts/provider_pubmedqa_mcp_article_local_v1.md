Answer one PubMedQA article-local benchmark case using PubTator-Link MCP tools.

Use the PubTator-Link MCP to answer as well as possible from biomedical evidence.

Recommended workflow:
1. Use target_pmids from the case as the article-local evidence set.
2. Call pubtator.preflight_review_sources for those PMIDs when available to learn whether full text or abstracts are available.
3. Call pubtator.get_publication_passages for those PMIDs. Prefer full text when the MCP exposes it; otherwise use abstract passages.
4. Decide only from MCP-returned evidence. Do not use outside biomedical knowledge.
5. If no relevant passage directly supports or contradicts the question, answer "maybe".

PubMedQA labels:
- "yes": retrieved passages directly support the question.
- "no": retrieved passages directly contradict the question.
- "maybe": retrieved passages are absent, indirect, underpowered, mixed, conditional, method-limited, or leave both yes and no plausible.

Return JSON only with exactly these keys:
{"case_id":"...","predicted_label":"yes|no|maybe","evidence_status":"supports|contradicts|insufficient|mixed","confidence":"high|medium|low","abstention_reason":"...","cited_pmids":[],"retrieved_pmids":[],"source_access":{"PMID":"full_text|abstract_only|metadata_only|missing"},"tool_workflow":"preflight_review_sources>get_publication_passages","mcp_experience":{"tool_discoverability":1,"context_quality":1,"context_size_control":1,"citation_support":1,"latency":1,"error_recovery":1,"workflow_ergonomics":1,"notes":"..."},"reason_short":"..."}

Use only PMIDs that were retrieved in cited_pmids. mcp_experience ratings must be integers from 1 to 10 from your perspective as an LLM consuming this MCP. Set abstention_reason to an empty string unless predicted_label is "maybe". Do not include markdown.

Case:
{{ case_json }}
