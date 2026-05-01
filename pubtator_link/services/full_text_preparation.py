"""Prepare review-scoped full-text evidence passages."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, cast

from structlog.typing import FilteringBoundLogger

from pubtator_link.config import ReviewReragConfig
from pubtator_link.models.review_rerag import (
    JobStatus,
    ReviewPassageRow,
    SourceCoverageHint,
    passage_id_for_pmcid,
    passage_id_for_pmid,
)

if TYPE_CHECKING:
    from pubtator_link.repositories.review_rerag import ReviewReragRepository

try:
    from pubtator_link.services.url_safety import SafeUrlFetcher as _ImportedSafeUrlFetcher
    from pubtator_link.services.url_safety import UrlSafetyError

    _SAFE_URL_FETCHER_CLS: Any | None = _ImportedSafeUrlFetcher
except ModuleNotFoundError:
    _SAFE_URL_FETCHER_CLS = None

    class UrlSafetyError(Exception):  # type: ignore[no-redef]
        """Fallback until the URL safety service is present in parallel worktrees."""


def looks_like_pdf(content: bytes) -> bool:
    """Return whether bytes start with a PDF header."""
    return content.startswith(b"%PDF")


def _passage_char_count(passages: list[ReviewPassageRow]) -> int:
    return sum(len(passage.text) for passage in passages)


class FullTextPreparationService:
    """Prepare PubTator and curated URL passages for review-scoped retrieval."""

    def __init__(
        self,
        config: ReviewReragConfig,
        repository: ReviewReragRepository,
        pubtator_client: Any,
        logger: FilteringBoundLogger | logging.Logger | None = None,
        safe_url_fetcher: Any | None = None,
        source_preflight_service: Any | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.pubtator_client = pubtator_client
        self.logger = logger or logging.getLogger(__name__)
        self.safe_url_fetcher = safe_url_fetcher
        self.source_preflight_service = source_preflight_service

    async def prepare_pmid(self, review_id: str, pmid: str) -> JobStatus:
        """Prepare passages for a PMID from full-text PubTator, then abstract fallback."""
        started = time.monotonic()
        coverage_hint = await self._coverage_hint_for_pmid(pmid)
        self.logger.info(
            "Review PMID preparation fetching full PubTator export",
            extra={"review_id": review_id, "pmid": pmid, "full": True},
        )
        full_data = await self.pubtator_client.export_publications(
            [pmid],
            format="biocjson",
            full=True,
        )
        full_retry_metadata = self._last_retry_metadata()
        passages = self._passages_from_export(
            review_id=review_id,
            export_data=full_data,
            source_kind="pubtator_full_bioc",
        )
        source_kind = "pubtator_full_bioc"
        self.logger.info(
            "Review PMID full PubTator export parsed",
            extra={
                "review_id": review_id,
                "pmid": pmid,
                "passage_count": len(passages),
                "char_count": _passage_char_count(passages),
            },
        )

        if passages:
            await self.repository.upsert_passages(passages)
            await self._record_pmid_attempt(
                review_id=review_id,
                pmid=pmid,
                source_kind="pubtator_full_bioc",
                status="success",
                reason=None,
                coverage_reason="full_text_available",
                coverage_hint=coverage_hint,
                retry_metadata=full_retry_metadata,
            )
            return "complete"

        await self._record_pmid_attempt(
            review_id=review_id,
            pmid=pmid,
            source_kind="pubtator_full_bioc",
            status="not_available",
            reason="No PubTator full-text passages found",
            coverage_reason=coverage_hint.coverage_reason if coverage_hint else "unknown",
            coverage_hint=coverage_hint,
            retry_metadata=full_retry_metadata,
        )

        if not passages:
            self.logger.info(
                "Review PMID preparation falling back to PubTator abstract export",
                extra={"review_id": review_id, "pmid": pmid, "full": False},
            )
            abstract_data = await self.pubtator_client.export_publications(
                [pmid],
                format="biocjson",
                full=False,
            )
            abstract_retry_metadata = self._last_retry_metadata()
            passages = self._passages_from_export(
                review_id=review_id,
                export_data=abstract_data,
                source_kind="pubtator_abstract",
            )
            source_kind = "pubtator_abstract"
            self.logger.info(
                "Review PMID abstract PubTator export parsed",
                extra={
                    "review_id": review_id,
                    "pmid": pmid,
                    "passage_count": len(passages),
                    "char_count": _passage_char_count(passages),
                },
            )
        else:
            abstract_retry_metadata = None

        if passages:
            self.logger.info(
                "Review PMID preparation upserting passages",
                extra={
                    "review_id": review_id,
                    "pmid": pmid,
                    "source_kind": source_kind,
                    "passage_count": len(passages),
                    "char_count": _passage_char_count(passages),
                },
            )
            await self.repository.upsert_passages(passages)

        status = "success" if passages else "failed"
        await self._record_pmid_attempt(
            review_id=review_id,
            pmid=pmid,
            source_kind=source_kind,
            status=status,
            reason=None if passages else "No PubTator passages found",
            coverage_reason="abstract_fallback_used" if passages else "unknown",
            coverage_hint=coverage_hint,
            retry_metadata=abstract_retry_metadata,
        )
        self.logger.info(
            "Review PMID preparation recorded retrieval attempt",
            extra={
                "review_id": review_id,
                "pmid": pmid,
                "source_kind": source_kind,
                "status": status,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )
        return "complete" if passages else "failed"

    async def _coverage_hint_for_pmid(self, pmid: str) -> SourceCoverageHint | None:
        if self.source_preflight_service is None:
            return None
        hints = await self.source_preflight_service.preflight_pmids([pmid])
        return hints[0] if hints else None

    def _last_retry_metadata(self) -> dict[str, Any]:
        metadata = getattr(self.pubtator_client, "last_retry_metadata", None)
        if metadata is None:
            return {}
        if hasattr(metadata, "__dict__"):
            return dict(metadata.__dict__)
        return dict(metadata)

    async def _record_pmid_attempt(
        self,
        *,
        review_id: str,
        pmid: str,
        source_kind: str,
        status: str,
        reason: str | None,
        coverage_reason: str,
        coverage_hint: SourceCoverageHint | None,
        retry_metadata: dict[str, Any] | None,
    ) -> None:
        retry_metadata = retry_metadata or {}
        await self.repository.record_retrieval_attempt(
            review_id,
            f"PMID:{pmid}",
            source_kind,
            status,
            content_type="application/json",
            reason=reason,
            coverage_reason=coverage_reason,
            attempt_count=int(retry_metadata.get("attempt_count") or 1),
            last_status_code=retry_metadata.get("last_status_code"),
            retry_after_ms=retry_metadata.get("retry_after_ms"),
            backoff_ms=retry_metadata.get("backoff_ms"),
            terminal_reason=retry_metadata.get("terminal_reason"),
            pmcid=coverage_hint.pmcid if coverage_hint else None,
            doi=coverage_hint.doi if coverage_hint else None,
            license_or_access_hint=(
                coverage_hint.license_or_access_hint if coverage_hint else None
            ),
            pmc_fallback_available=(
                coverage_hint.pmc_fallback_available if coverage_hint else False
            ),
        )

    async def prepare_curated_url(self, review_id: str, url: str) -> JobStatus:
        """Prepare a curated URL PDF if a supported parser is available."""
        fetcher = self.safe_url_fetcher
        if fetcher is None:
            if _SAFE_URL_FETCHER_CLS is None:
                raise RuntimeError("SafeUrlFetcher is not available")
            fetcher = _SAFE_URL_FETCHER_CLS(self.config)

        try:
            content, content_type = await self._fetch_curated_url(fetcher, url)
        except UrlSafetyError as exc:
            await self.repository.record_retrieval_attempt(
                review_id,
                url,
                "curated_pdf",
                "blocked",
                url=url,
                content_type=None,
                reason=str(exc),
            )
            return "failed"

        if not looks_like_pdf(content):
            await self.repository.record_retrieval_attempt(
                review_id,
                url,
                self._source_kind_for_content_type(content_type),
                "blocked",
                url=url,
                content_type=content_type,
                content_length=len(content),
                reason="Curated URL did not return PDF bytes",
            )
            return "failed"

        if not self.config.enable_docling:
            await self.repository.record_retrieval_attempt(
                review_id,
                url,
                "docling_pdf",
                "not_available",
                url=url,
                content_type=content_type,
                content_length=len(content),
                reason="Docling PDF preparation is disabled",
            )
            return "failed"

        await self.repository.record_retrieval_attempt(
            review_id,
            url,
            "docling_pdf",
            "not_available",
            url=url,
            content_type=content_type,
            content_length=len(content),
            reason="Docling PDF preparation is not implemented",
        )
        return "failed"

    def passages_from_bioc_document(
        self,
        review_id: str,
        document: dict[str, Any],
        source_kind: str,
    ) -> list[ReviewPassageRow]:
        """Build deterministic review passage rows from one BioC document."""
        pmid = self._string_or_none(document.get("pmid")) or self._pmid_from_document_id(document)
        pmcid = self._string_or_none(document.get("pmcid"))
        source_id = (
            f"PMID:{pmid}" if pmid else f"PMCID:{pmcid}" if pmcid else str(document.get("id"))
        )
        rows: list[ReviewPassageRow] = []

        for index, passage in enumerate(document.get("passages", [])):
            if not isinstance(passage, dict):
                continue

            text = self._string_or_none(passage.get("text"))
            if not text:
                continue

            section = self._section_from_passage(passage)
            if pmid:
                passage_id = passage_id_for_pmid(pmid, section, index)
            elif pmcid:
                passage_id = passage_id_for_pmcid(pmcid, section, index)
            else:
                passage_id = f"{source_id}:{index}"

            rows.append(
                ReviewPassageRow(
                    passage_id=passage_id,
                    review_id=review_id,
                    source_id=source_id,
                    source_kind=source_kind,
                    section=section,
                    text=text,
                    pmid=pmid,
                    pmcid=pmcid,
                    doi=self._string_or_none(document.get("doi")),
                    heading_path=self._heading_path_from_passage(passage),
                    source_metadata={"document_id": document.get("id")},
                )
            )

        return rows

    def _passages_from_export(
        self,
        review_id: str,
        export_data: dict[str, Any],
        source_kind: str,
    ) -> list[ReviewPassageRow]:
        rows: list[ReviewPassageRow] = []
        for document in _extract_documents(export_data):
            rows.extend(
                self.passages_from_bioc_document(
                    review_id=review_id,
                    document=document,
                    source_kind=source_kind,
                )
            )
        return rows

    @staticmethod
    def _section_from_passage(passage: dict[str, Any]) -> str:
        infons = passage.get("infons")
        if not isinstance(infons, dict):
            infons = {}

        for key in ("section_type", "section", "type", "passage_type"):
            value = infons.get(key) or passage.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return "body"

    @staticmethod
    def _heading_path_from_passage(passage: dict[str, Any]) -> str | None:
        infons = passage.get("infons")
        if isinstance(infons, dict):
            heading = infons.get("heading_path") or infons.get("section")
            if isinstance(heading, str) and heading.strip():
                return heading.strip()
        return None

    @staticmethod
    def _pmid_from_document_id(document: dict[str, Any]) -> str | None:
        document_id = document.get("id") or document.get("_id")
        if document_id is None:
            return None

        candidate = str(document_id).split("|", 1)[0]
        return candidate if candidate.isdigit() else None

    @staticmethod
    def _source_kind_for_content_type(content_type: str) -> str:
        return "curated_html" if "html" in content_type.lower() else "curated_pdf"

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    async def _fetch_curated_url(self, fetcher: Any, url: str) -> tuple[bytes, str]:
        try:
            return cast(
                tuple[bytes, str],
                await fetcher.fetch(url, max_bytes=self.config.pdf_max_bytes),
            )
        except TypeError:
            return cast(tuple[bytes, str], await fetcher.fetch(url))


def _extract_documents(export_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract BioC documents from PubTator3 response shapes."""
    if "PubTator3" in export_data:
        return _dict_documents(export_data["PubTator3"])

    if "documents" in export_data:
        return _dict_documents(export_data["documents"])

    content = export_data.get("content")
    if isinstance(content, str) and content.strip():
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, dict):
            return _extract_documents(parsed)
        return _dict_documents(parsed)

    return _dict_documents(export_data)


def _dict_documents(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        if "passages" in value:
            return [value]
        return _extract_documents(value)
    return []
