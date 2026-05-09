Answer one PubMedQA article-local benchmark case.

PubMedQA labels are yes, no, and maybe. The label should reflect what the supplied abstract context establishes about the research question, not what outside biomedical knowledge suggests.

Use only the supplied case text. Do not use outside biomedical knowledge to rescue an answer.

Decision policy:
- Choose "yes" when the abstract context directly supports the question's main claim.
- Choose "no" when the abstract context directly contradicts or rejects the question's main claim.
- Choose "maybe" when the abstract context does not settle the exact question, including when evidence is mixed, indirect, underpowered, conditional, observational-only for a causal/recommendation question, based on beliefs/practices rather than outcomes, or narrower than the question.
- If a study result supports only a qualified version of the question but not the broad question as written, choose "maybe".
- Do not choose "maybe" merely because all biomedical studies have limitations; choose it when the supplied abstract itself leaves the question unresolved or materially qualified.

Synthetic calibration examples:
- Question: Does intervention A reduce biomarker B? Context: A randomized trial reports biomarker B was significantly lower with intervention A than placebo and concludes intervention A reduced biomarker B. Label: yes.
- Question: Does supplement C improve survival? Context: Survival did not differ between supplement C and control, and the abstract concludes supplement C did not improve survival. Label: no.
- Question: Does equipment D prevent concussion? Context: The study surveys players' and coaches' beliefs about equipment D but does not measure concussion incidence or prevention. Label: maybe.
- Question: Should procedure E be used routinely? Context: The study shows procedure E is feasible in a selected retrospective cohort but provides no direct comparator and says further study is needed. Label: maybe.

Return JSON only with exactly these keys:
{"case_id":"...","predicted_label":"yes|no|maybe","evidence_status":"supports|contradicts|insufficient|mixed","confidence":"high|medium|low","abstention_reason":"...","cited_pmids":[],"reason_short":"..."}

Set abstention_reason to an empty string unless predicted_label is "maybe".
Keep reason_short to one concise evidence-based sentence. Do not include markdown.

Case:
{{ case_json }}
