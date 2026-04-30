"""Compact publication passage service."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from pubtator_link.models.publication_passages import (
    PassageDropReason,
    PublicationContextEstimate,
    PublicationContextEstimateRequest,
    PublicationContextEstimateResponse,
    PublicationPassage,
    PublicationPassageMode,
    PublicationPassageRequest,
    PublicationPassageResponse,
    PublicationPassageSource,
)
from pubtator_link.models.review_rerag import normalize_section, passage_id_for_pmid


class PublicationServiceLike(Protocol):
    """Small protocol for the injected publication service."""

    async def export_publications_list(
        self, pmids: list[str], format: str, full: bool
    ) -> dict[str, Any]: ...


SECTION_ALIASES = {
    "abstr": "abstract",
    "abstract": "abstract",
    "discuss": "discussion",
    "concl": "conclusion",
    "ref": "references",
    "references": "references",
    "table": "table",
}


class PublicationPassageService:
    """Build compact passages from PubTator BioC-like publication exports."""

    def __init__(
        self,
        publication_service: PublicationServiceLike,
        logger: logging.Logger | None = None,
    ) -> None:
        self.publication_service = publication_service
        self.logger = logger or logging.getLogger(__name__)

    async def get_passages(self, request: PublicationPassageRequest) -> PublicationPassageResponse:
        """Return compact passages while enforcing filters and budgets."""
        source = self._source_for_request(request.full)
        try:
            export_data = await self.publication_service.export_publications_list(
                request.pmids,
                format="biocjson",
                full=request.full,
            )
        except Exception as exc:
            estimate = PublicationContextEstimate(
                estimated_passages=0,
                estimated_chars=0,
                sections_by_pmid={pmid: [] for pmid in request.pmids},
                recommended_mode=request.mode,
                warning="Publication export failed",
            )
            return PublicationPassageResponse(
                success=False,
                pmids=request.pmids,
                mode=request.mode,
                passages=[],
                dropped=[
                    PassageDropReason(
                        reason="upstream_error",
                        message=str(exc),
                    )
                ],
                context_estimate=estimate,
            )

        passages, dropped = self._compact_export(
            export_data=export_data,
            pmids=request.pmids,
            source=source,
            sections=request.sections,
            include_tables=request.include_tables,
            include_references=request.include_references,
            max_passages_per_pmid=request.max_passages_per_pmid,
        )
        passages, budget_drops = self._apply_char_budget(passages, request.max_chars)
        dropped.extend(budget_drops)
        estimate = self._estimate_from_passages(passages, request.pmids, request.mode)

        return PublicationPassageResponse(
            success=True,
            pmids=request.pmids,
            mode=request.mode,
            passages=passages,
            dropped=dropped,
            context_estimate=estimate,
        )

    async def estimate_context(
        self, request: PublicationContextEstimateRequest
    ) -> PublicationContextEstimateResponse:
        """Estimate compact passage counts and characters without raw BioC output."""
        source = self._source_for_request(request.full)
        try:
            export_data = await self.publication_service.export_publications_list(
                request.pmids,
                format="biocjson",
                full=request.full,
            )
        except Exception as exc:
            return PublicationContextEstimateResponse(
                success=False,
                pmids=request.pmids,
                mode=request.mode,
                estimated_passages=0,
                estimated_chars=0,
                sections_by_pmid={pmid: [] for pmid in request.pmids},
                recommended_mode=request.mode,
                warning=f"Publication export failed: {exc}",
            )

        passages, _ = self._compact_export(
            export_data=export_data,
            pmids=request.pmids,
            source=source,
            sections=request.sections,
            include_tables=request.include_tables,
            include_references=request.include_references,
            max_passages_per_pmid=request.max_passages_per_pmid,
        )
        estimate = self._estimate_from_passages(passages, request.pmids, request.mode)
        warning = estimate.warning
        if request.full and warning is None:
            warning = "Full PubTator BioC can be large; compact passages are recommended."

        return PublicationContextEstimateResponse(
            success=True,
            pmids=request.pmids,
            mode=request.mode,
            estimated_passages=estimate.estimated_passages,
            estimated_chars=estimate.estimated_chars,
            sections_by_pmid=estimate.sections_by_pmid,
            recommended_mode=estimate.recommended_mode,
            warning=warning,
        )

    def _compact_export(
        self,
        export_data: dict[str, Any],
        pmids: list[str],
        source: PublicationPassageSource,
        sections: list[str],
        include_tables: bool,
        include_references: bool,
        max_passages_per_pmid: int,
    ) -> tuple[list[PublicationPassage], list[PassageDropReason]]:
        section_filter = {normalize_publication_section(section) for section in sections}
        passages: list[PublicationPassage] = []
        dropped: list[PassageDropReason] = []
        per_pmid_counts: dict[str, int] = {}

        for document in _extract_documents(export_data):
            pmid = _pmid_from_document(document)
            if pmid is None:
                continue
            pmcid = _pmcid_from_document(document)
            section_counts: dict[str, int] = {}

            for raw_passage in document.get("passages", []):
                if not isinstance(raw_passage, dict):
                    continue

                text = _string_or_none(raw_passage.get("text"))
                if not text:
                    continue

                section = normalize_publication_section(_section_from_passage(raw_passage))
                section_index = section_counts.get(section, 0)
                section_counts[section] = section_index + 1
                passage_id = passage_id_for_pmid(pmid, section, section_index)
                drop = self._drop_reason_for_passage(
                    pmid=pmid,
                    section=section,
                    passage_id=passage_id,
                    section_filter=section_filter,
                    include_tables=include_tables,
                    include_references=include_references,
                )
                if drop is not None:
                    dropped.append(drop)
                    continue

                current_count = per_pmid_counts.get(pmid, 0)
                if current_count >= max_passages_per_pmid:
                    dropped.append(
                        PassageDropReason(
                            reason="max_passages_per_pmid_exceeded",
                            pmid=pmid,
                            section=section,
                            passage_id=passage_id,
                        )
                    )
                    continue

                passages.append(
                    PublicationPassage(
                        passage_id=passage_id,
                        pmid=pmid,
                        pmcid=pmcid,
                        section=section,
                        text=text,
                        char_count=len(text),
                        source=source,
                    )
                )
                per_pmid_counts[pmid] = current_count + 1

        return passages, dropped

    @staticmethod
    def _drop_reason_for_passage(
        pmid: str,
        section: str,
        passage_id: str,
        section_filter: set[str],
        include_tables: bool,
        include_references: bool,
    ) -> PassageDropReason | None:
        if section == "references" and not include_references:
            return PassageDropReason(
                reason="reference_excluded",
                pmid=pmid,
                section=section,
                passage_id=passage_id,
            )
        if section == "table" and not include_tables:
            return PassageDropReason(
                reason="table_excluded",
                pmid=pmid,
                section=section,
                passage_id=passage_id,
            )
        if section_filter and section not in section_filter:
            return PassageDropReason(
                reason="section_filtered",
                pmid=pmid,
                section=section,
                passage_id=passage_id,
            )
        return None

    @staticmethod
    def _apply_char_budget(
        passages: list[PublicationPassage],
        max_chars: int,
    ) -> tuple[list[PublicationPassage], list[PassageDropReason]]:
        kept: list[PublicationPassage] = []
        dropped: list[PassageDropReason] = []
        used_chars = 0

        for passage in passages:
            if used_chars + passage.char_count > max_chars:
                dropped.append(
                    PassageDropReason(
                        reason="char_budget_exceeded",
                        pmid=passage.pmid,
                        section=passage.section,
                        passage_id=passage.passage_id,
                    )
                )
                continue

            kept.append(passage)
            used_chars += passage.char_count

        return kept, dropped

    @staticmethod
    def _estimate_from_passages(
        passages: list[PublicationPassage],
        pmids: list[str],
        mode: PublicationPassageMode,
    ) -> PublicationContextEstimate:
        sections_by_pmid: dict[str, list[str]] = {pmid: [] for pmid in pmids}
        for passage in passages:
            sections = sections_by_pmid.setdefault(passage.pmid, [])
            if passage.section not in sections:
                sections.append(passage.section)

        estimated_chars = sum(passage.char_count for passage in passages)
        warning = None
        if estimated_chars > 12000:
            warning = "Estimated context is large; consider section filters or abstracts mode."

        return PublicationContextEstimate(
            estimated_passages=len(passages),
            estimated_chars=estimated_chars,
            sections_by_pmid=sections_by_pmid,
            recommended_mode="compact_passages" if mode == "section_text" else mode,
            warning=warning,
        )

    @staticmethod
    def _source_for_request(full: bool) -> PublicationPassageSource:
        return "pubtator_full_bioc" if full else "pubtator_abstract"


def normalize_publication_section(section: str) -> str:
    """Normalize PubTator section names with publication-specific aliases."""
    normalized = normalize_section(section)
    return SECTION_ALIASES.get(normalized, normalized)


def _extract_documents(export_data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = [
        export_data.get("documents"),
        export_data.get("export_data", {}).get("documents")
        if isinstance(export_data.get("export_data"), dict)
        else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [document for document in candidate if isinstance(document, dict)]
    return []


def _section_from_passage(passage: dict[str, Any]) -> str:
    infons = passage.get("infons")
    if not isinstance(infons, dict):
        infons = {}

    for key in ("section_type", "section", "type", "passage_type"):
        value = infons.get(key) or passage.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return "body"


def _pmid_from_document(document: dict[str, Any]) -> str | None:
    value = document.get("pmid") or document.get("id") or document.get("_id")
    if value is None:
        return None

    candidate = str(value).split("|", 1)[0]
    return candidate if candidate.isdigit() else None


def _pmcid_from_document(document: dict[str, Any]) -> str | None:
    value = document.get("pmcid")
    infons = document.get("infons")
    if value is None and isinstance(infons, dict):
        value = infons.get("pmcid")
    return _string_or_none(value)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
