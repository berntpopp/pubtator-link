Answer one PubMedQA article-local benchmark case.

PubMedQA labels are yes, no, and maybe. In this benchmark, "maybe" is the label for uncertainty from the supplied evidence. Treat it like "unanswerable from this evidence", not like a casual hedge.

Use only the supplied case text. Do not use outside biomedical knowledge to rescue an answer.

Decision policy:
- Choose "yes" only when the supplied evidence directly supports the question.
- Choose "no" only when the supplied evidence directly contradicts the question.
- Choose "maybe" when evidence is absent, indirect, underpowered, mixed, conditional, method-limited, or leaves both yes and no plausible.
- If you are uncertain between a binary label and "maybe", choose "maybe".

Return JSON only with exactly these keys:
{"case_id":"...","predicted_label":"yes|no|maybe","evidence_status":"supports|contradicts|insufficient|mixed","confidence":"high|medium|low","abstention_reason":"...","cited_pmids":[],"reason_short":"..."}

Set abstention_reason to an empty string unless predicted_label is "maybe".
Keep reason_short to one concise evidence-based sentence. Do not include markdown.

Case:
{{ case_json }}
