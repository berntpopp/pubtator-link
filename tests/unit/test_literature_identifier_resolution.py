from __future__ import annotations

import pytest

from pubtator_link.models.discovery import ArticleIdConversionRecord
from pubtator_link.services.literature_identifier_resolution import DoiPmidResolver


class RecordingDiscovery:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        self.calls.append((ids, source))
        return type(
            "ArticleIdConversionResponse",
            (),
            {
                "records": [
                    ArticleIdConversionRecord(
                        input_id="10.1000/a",
                        input_kind="doi",
                        status="resolved",
                        pmid="100",
                        doi="10.1000/a",
                    ),
                    ArticleIdConversionRecord(
                        input_id="10.1000/b",
                        input_kind="doi",
                        status="unresolved",
                        doi="10.1000/b",
                    ),
                ]
            },
        )()


@pytest.mark.asyncio
async def test_resolver_batches_caches_positive_and_negative_results() -> None:
    discovery = RecordingDiscovery()
    resolver = DoiPmidResolver(discovery_service=discovery)

    first = await resolver.resolve(["10.1000/a", "10.1000/b"], max_ids=20)
    second = await resolver.resolve(["10.1000/a", "10.1000/b"], max_ids=20)

    assert first.resolved == {"10.1000/a": "100"}
    assert first.unresolved == {"10.1000/b"}
    assert second.resolved == {"10.1000/a": "100"}
    assert second.cached_count == 2
    assert discovery.calls == [(["10.1000/a", "10.1000/b"], "doi")]


@pytest.mark.asyncio
async def test_resolver_respects_max_ids_and_reports_skipped() -> None:
    discovery = RecordingDiscovery()
    resolver = DoiPmidResolver(discovery_service=discovery)

    result = await resolver.resolve(["10.1000/a", "10.1000/b"], max_ids=1)

    assert discovery.calls == [(["10.1000/a"], "doi")]
    assert result.skipped_count == 1
