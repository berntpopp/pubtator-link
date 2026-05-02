from __future__ import annotations

from typing import Any, ClassVar

import httpx

from pubtator_link.api.client import PubTator3Client


class AsyncClientDouble:
    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    async def aclose(self) -> None:
        return None


def test_pubtator_client_configures_explicit_http_limits(monkeypatch) -> None:
    AsyncClientDouble.calls = []
    monkeypatch.setattr("pubtator_link.api.client.httpx.AsyncClient", AsyncClientDouble)

    PubTator3Client()

    assert len(AsyncClientDouble.calls) == 2
    for call in AsyncClientDouble.calls:
        assert isinstance(call["limits"], httpx.Limits)
        assert call["limits"].max_connections is not None
        assert call["limits"].max_keepalive_connections is not None
