Answer one PubMedQA article-local benchmark case.

Decide only from the supplied case text. Do not use outside medical knowledge unless the case itself supports the conclusion.

Use these labels:
- "yes": the supplied evidence directly supports the question.
- "no": the supplied evidence directly contradicts the question.
- "maybe": the supplied evidence is mixed, indirect, underpowered, incomplete, or insufficient for a clear yes/no.

Before choosing, check whether both a yes and no interpretation remain plausible from the supplied evidence. If they do, choose "maybe". Do not force a binary answer when the evidence is ambiguous.

Return JSON only with exactly these keys:
{"case_id":"...","predicted_label":"yes|no|maybe","cited_pmids":[],"reason_short":"..."}

Keep reason_short to one concise evidence-based sentence. Do not include markdown.

Case:
{{ case_json }}
