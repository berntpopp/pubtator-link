Answer one PubMedQA article-local benchmark case.

PubMedQA labels are yes, no, and maybe. Answer using your own model capabilities and any native non-PubTator tools available to you, such as web search, if your runtime exposes them.

Do not use PubTator-Link MCP tools. Do not assume any hidden abstract or gold answer is available. The case contains only the question and case identifier.

Decision policy:
- Choose "yes" when the evidence you can access directly supports the question's main claim.
- Choose "no" when the evidence you can access directly contradicts or rejects the question's main claim.
- Choose "maybe" when accessible evidence does not settle the exact question, including when evidence is mixed, indirect, underpowered, conditional, observational-only for a causal/recommendation question, based on beliefs/practices rather than outcomes, or narrower than the question.
- If a study result supports only a qualified version of the question but not the broad question as written, choose "maybe".
- If accessible evidence contains a clear direction but important limitations prevent a definitive yes/no answer, choose "maybe".
- Do not choose "maybe" merely because all biomedical studies have limitations; choose it when the accessible evidence itself leaves the question unresolved or materially qualified.

Return JSON only with exactly these keys:
{"case_id":"...","predicted_label":"yes|no|maybe","evidence_status":"supports|contradicts|insufficient|mixed","confidence":"high|medium|low","abstention_reason":"...","cited_pmids":[],"reason_short":"..."}

Set abstention_reason to an empty string unless predicted_label is "maybe".
Keep reason_short to one concise evidence-based sentence. Do not include markdown.

Case:
{{ case_json }}
