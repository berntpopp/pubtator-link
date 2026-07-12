"""F-18 regression: SECURITY.md must document the required GitHub secret-scanning
repository settings and the operator commands to enable and verify them.

Secret scanning / push protection are repository settings, not a workflow, so the
PR can only *document* them; the operator runs the `gh api` PATCH out of band.
This test keeps that documentation from silently disappearing.
"""

from __future__ import annotations

from pathlib import Path

SECURITY_DOC = Path("docs/SECURITY.md").read_text(encoding="utf-8")


def test_security_doc_documents_secret_scanning_settings() -> None:
    for token in (
        "secret_scanning",
        "secret_scanning_push_protection",
        "security_and_analysis",
        # operator enable + verify commands
        "gh api -X PATCH repos/berntpopp/pubtator-link",
        "gh api repos/berntpopp/pubtator-link --jq '.security_and_analysis'",
    ):
        assert token in SECURITY_DOC, f"SECURITY.md must document {token!r}"
