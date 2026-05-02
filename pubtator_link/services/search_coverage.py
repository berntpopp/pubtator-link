from __future__ import annotations

from typing import Literal, Protocol, cast

from pubtator_link.models.responses import CoveragePreflightError, SearchResponse
from pubtator_link.models.review_rerag import SourceCoverageHint

SearchCoverageMode = Literal["none", "preflight"]


class SearchCoveragePreflight(Protocol):
    """Service capable of estimating source coverage for search PMIDs."""

    async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]: ...


async def attach_preflight_coverage(
    response: SearchResponse,
    preflight_service: SearchCoveragePreflight,
) -> None:
    """Attach per-result source coverage hints, degrading without failing search."""
    pmids = [result.pmid for result in response.results if result.pmid]
    if not pmids:
        return

    try:
        hints = await preflight_service.preflight_pmids(pmids)
    except Exception as exc:
        reason = _preflight_error_reason(exc)
        response.message = (
            "Coverage preflight failed; search results returned without coverage hints."
        )
        response.source_versions["coverage_preflight"] = "failed"
        response.preflight_failure_reason = reason
        response.preflight_error_reason = reason
        response.preflight_error_code = f"coverage_preflight_{reason}"
        response.preflight_error = _preflight_error(reason)
        return

    hints_by_pmid = {hint.pmid: hint.model_dump(mode="json") for hint in hints}
    for result in response.results:
        hint = hints_by_pmid.get(result.pmid)
        if hint is None:
            continue
        result.coverage_hint = None if _coverage_hint_has_no_signal(hint) else hint
        result.preflight_coverage_guess = hint.get("expected_coverage")
        result.preflight_coverage_reason = hint.get("coverage_reason")
        result.preflight_confidence = cast(
            Literal["high", "medium", "low"],
            _preflight_confidence(
                str(hint.get("expected_coverage") or "unknown"),
                str(hint.get("coverage_reason") or "unknown"),
            ),
        )
    response.source_versions["coverage_preflight"] = "included"


def _preflight_error_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ConnectionError):
        return "upstream_unavailable"
    if isinstance(exc, ValueError):
        return "converter_failed"
    return "internal_error"


def _preflight_error(reason: str) -> CoveragePreflightError:
    code = f"coverage_preflight_{reason}"
    retryable = reason in {"timeout", "upstream_unavailable"}
    messages = {
        "timeout": "Coverage preflight timed out; retrying may succeed.",
        "upstream_unavailable": "Coverage preflight upstream was unavailable; retrying may succeed.",
        "converter_failed": "Coverage preflight identifier conversion failed; revise identifiers before retrying.",
        "internal_error": "Coverage preflight hit an internal error; do not retry blindly.",
    }
    return CoveragePreflightError(
        code=code,
        reason=reason,
        retryable=retryable,
        message=messages.get(reason, "Coverage preflight failed."),
    )


def _preflight_confidence(expected_coverage: str, coverage_reason: str) -> str:
    if expected_coverage == "full_text":
        return "high"
    if expected_coverage == "abstract_only":
        return "low" if coverage_reason == "pre_resolution_best_guess" else "medium"
    return "low"


def _coverage_hint_has_no_signal(hint: dict[str, object]) -> bool:
    signal_keys = {
        "pmcid",
        "doi",
        "license_or_access_hint",
        "notes",
        "resolver_attempts",
    }
    if any(hint.get(key) for key in signal_keys):
        return False
    if hint.get("pmc_fallback_available"):
        return False
    return (
        hint.get("expected_coverage", "unknown") == "unknown"
        and hint.get("coverage_reason", "unknown") == "unknown"
    )
