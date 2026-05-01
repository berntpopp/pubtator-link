from typing import Any

import pytest

from pubtator_link.config import ReviewReragConfig
from pubtator_link.models.review_rerag import ReviewPassageRow, SourceCoverageHint
from pubtator_link.services.full_text_preparation import (
    FullTextPreparationService,
    looks_like_pdf,
)


def _config(*, enable_docling: bool = False) -> ReviewReragConfig:
    return ReviewReragConfig(
        database_url=None,
        prep_concurrency=2,
        document_timeout_seconds=60,
        source_timeout_seconds=5,
        pdf_max_bytes=64,
        text_max_bytes=64,
        allow_http_urls=False,
        enable_docling=enable_docling,
        enable_europe_pmc_fallback=False,
    )


class RecordingRepository:
    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []
        self.passages: list[ReviewPassageRow] = []

    async def record_retrieval_attempt(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        self.attempts.append(
            {
                "review_id": review_id,
                "source_id": source_id,
                "source_kind": source_kind,
                "status": status,
                **kwargs,
            }
        )

    async def upsert_passages(self, passages: list[ReviewPassageRow]) -> None:
        self.passages.extend(passages)


class RecordingPubTatorClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.retry_metadata_by_call: list[dict[str, Any]] = []
        self.last_retry_metadata: dict[str, Any] | None = None

    async def export_publications(
        self, pmids: list[str], format: str = "biocjson", full: bool = False
    ) -> dict[str, Any]:
        self.calls.append({"pmids": pmids, "format": format, "full": full})
        self.last_retry_metadata = (
            self.retry_metadata_by_call.pop(0) if self.retry_metadata_by_call else None
        )
        return self.responses.pop(0)


class StaticPreflightService:
    def __init__(self, hint: SourceCoverageHint) -> None:
        self.hint = hint
        self.calls: list[list[str]] = []

    async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
        self.calls.append(pmids)
        return [self.hint]


class FakeEuropePmcClient:
    def __init__(self) -> None:
        self.lookup_calls: list[str] = []
        self.fetch_calls: list[str] = []

    async def lookup_open_access_record(self, pmcid_or_pmid: str):
        from pubtator_link.services.europe_pmc import EuropePmcLookupResult

        self.lookup_calls.append(pmcid_or_pmid)
        return EuropePmcLookupResult(
            available=True,
            pmcid="PMC123",
            license_or_access_hint="CC BY",
            full_text_url="https://example.org/full.xml",
            reason="full_text_available",
        )

    async def fetch_full_text_xml(self, url: str) -> str:
        self.fetch_calls.append(url)
        return """
        <article>
          <front>
            <article-meta>
              <title-group><article-title>FMF title</article-title></title-group>
              <abstract><p>Europe PMC abstract passage.</p></abstract>
            </article-meta>
          </front>
          <body><sec><title>Results</title><p>Europe PMC result passage.</p></sec></body>
        </article>
        """


class StaticFetcher:
    def __init__(self, body: bytes, content_type: str) -> None:
        self.body = body
        self.content_type = content_type
        self.calls: list[dict[str, Any]] = []

    async def fetch(self, url: str, max_bytes: int | None = None) -> tuple[bytes, str]:
        self.calls.append({"url": url, "max_bytes": max_bytes})
        return self.body, self.content_type


def test_looks_like_pdf_only_accepts_pdf_magic_bytes() -> None:
    assert looks_like_pdf(b"%PDF-1.7\nbody")
    assert not looks_like_pdf(b" \n%PDF-1.7\nbody")
    assert not looks_like_pdf(b"<!doctype html><title>not a pdf</title>")
    assert not looks_like_pdf(b"")


def test_passages_from_bioc_document_builds_deterministic_passage_rows() -> None:
    service = FullTextPreparationService(
        config=_config(),
        repository=RecordingRepository(),
        pubtator_client=RecordingPubTatorClient([]),
    )
    document = {
        "id": "40234174",
        "pmid": 40234174,
        "pmcid": "PMC123",
        "passages": [
            {"infons": {"type": "title"}, "text": "Clinical FMF diagnosis."},
            {
                "infons": {"section_type": "Methods & Results"},
                "text": "Colchicine response was measured.",
            },
        ],
    }

    passages = service.passages_from_bioc_document(
        review_id="review-1",
        document=document,
        source_kind="pubtator_full_bioc",
    )

    assert [passage.passage_id for passage in passages] == [
        "PMID:40234174:title:0",
        "PMID:40234174:methods_results:1",
    ]
    assert all(passage.review_id == "review-1" for passage in passages)
    assert all(passage.pmid == "40234174" for passage in passages)
    assert passages[0].source_id == "PMID:40234174"
    assert passages[1].section == "Methods & Results"


@pytest.mark.asyncio
async def test_prepare_pmid_falls_back_to_abstract_and_records_passages() -> None:
    repository = RecordingRepository()
    pubtator_client = RecordingPubTatorClient(
        [
            {"PubTator3": [{"id": "40234174", "pmid": "40234174", "passages": []}]},
            {
                "documents": [
                    {
                        "id": "40234174",
                        "pmid": "40234174",
                        "passages": [
                            {
                                "infons": {"type": "abstract"},
                                "text": "Colchicine should start after diagnosis.",
                            }
                        ],
                    }
                ]
            },
        ]
    )
    pubtator_client.retry_metadata_by_call = [
        {
            "attempt_count": 3,
            "last_status_code": 503,
            "retry_after_ms": 1000,
            "backoff_ms": 750,
            "terminal_reason": "retry_exhausted",
        },
        {"attempt_count": 1, "last_status_code": 200},
    ]
    preflight = StaticPreflightService(
        SourceCoverageHint(
            pmid="40234174",
            expected_coverage="abstract_only",
            coverage_reason="no_pmcid",
            pmcid="PMC123",
            doi="10.1000/example",
            license_or_access_hint="oa",
            pmc_fallback_available=True,
        )
    )
    service = FullTextPreparationService(
        config=_config(),
        repository=repository,
        pubtator_client=pubtator_client,
        source_preflight_service=preflight,
    )

    status = await service.prepare_pmid(review_id="review-1", pmid="40234174")

    assert status == "complete"
    assert pubtator_client.calls == [
        {"pmids": ["40234174"], "format": "biocjson", "full": True},
        {"pmids": ["40234174"], "format": "biocjson", "full": False},
    ]
    assert [passage.passage_id for passage in repository.passages] == ["PMID:40234174:abstract:0"]
    assert repository.passages[0].source_kind == "pubtator_abstract"
    assert repository.attempts == [
        {
            "review_id": "review-1",
            "source_id": "PMID:40234174",
            "source_kind": "pubtator_full_bioc",
            "status": "not_available",
            "content_type": "application/json",
            "reason": "No PubTator full-text passages found",
            "coverage_reason": "no_pmcid",
            "attempt_count": 3,
            "last_status_code": 503,
            "retry_after_ms": 1000,
            "backoff_ms": 750,
            "terminal_reason": "retry_exhausted",
            "pmcid": "PMC123",
            "doi": "10.1000/example",
            "license_or_access_hint": "oa",
            "pmc_fallback_available": True,
        },
        {
            "review_id": "review-1",
            "source_id": "PMID:40234174",
            "source_kind": "pubtator_abstract",
            "status": "success",
            "content_type": "application/json",
            "reason": None,
            "coverage_reason": "abstract_fallback_used",
            "attempt_count": 1,
            "last_status_code": 200,
            "retry_after_ms": None,
            "backoff_ms": None,
            "terminal_reason": None,
            "pmcid": "PMC123",
            "doi": "10.1000/example",
            "license_or_access_hint": "oa",
            "pmc_fallback_available": True,
        },
    ]
    assert preflight.calls == [["40234174"]]


@pytest.mark.asyncio
async def test_prepare_pmid_uses_enabled_europe_pmc_before_abstract_fallback() -> None:
    repository = RecordingRepository()
    pubtator_client = RecordingPubTatorClient(
        [{"PubTator3": [{"id": "40234174", "pmid": "40234174", "passages": []}]}]
    )
    europe_pmc = FakeEuropePmcClient()
    config = _config()
    config = ReviewReragConfig(
        **{**config.__dict__, "enable_europe_pmc_fallback": True}
    )
    service = FullTextPreparationService(
        config=config,
        repository=repository,
        pubtator_client=pubtator_client,
        europe_pmc_client=europe_pmc,
    )

    status = await service.prepare_pmid(review_id="review-1", pmid="40234174")

    assert status == "complete"
    assert europe_pmc.lookup_calls == ["40234174"]
    assert europe_pmc.fetch_calls == ["https://example.org/full.xml"]
    assert [passage.source_kind for passage in repository.passages] == [
        "europe_pmc_jats",
        "europe_pmc_jats",
        "europe_pmc_jats",
    ]
    assert repository.attempts[-1]["source_kind"] == "europe_pmc_jats"
    assert repository.attempts[-1]["status"] == "success"


@pytest.mark.asyncio
async def test_prepare_curated_url_records_blocked_html_as_failed() -> None:
    repository = RecordingRepository()
    fetcher = StaticFetcher(
        body=b"<!doctype html><title>blocked</title>",
        content_type="text/html",
    )
    service = FullTextPreparationService(
        config=_config(),
        repository=repository,
        pubtator_client=RecordingPubTatorClient([]),
        safe_url_fetcher=fetcher,
    )

    status = await service.prepare_curated_url(
        review_id="review-1",
        url="https://example.test/not-pdf",
    )

    assert status == "failed"
    assert fetcher.calls == [{"url": "https://example.test/not-pdf", "max_bytes": 64}]
    assert repository.passages == []
    assert repository.attempts == [
        {
            "review_id": "review-1",
            "source_id": "https://example.test/not-pdf",
            "source_kind": "curated_html",
            "status": "blocked",
            "url": "https://example.test/not-pdf",
            "content_type": "text/html",
            "content_length": 37,
            "reason": "Curated URL did not return PDF bytes",
        }
    ]
