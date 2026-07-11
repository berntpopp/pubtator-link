"""PubTator3 API client with rate limiting and error handling."""

import asyncio
import json
import time
from typing import Any

import httpx
from structlog.typing import FilteringBoundLogger

from ..config import APIConfig, TextProcessingConfig, api_config, text_processing_config
from ..logging_config import log_api_request, log_rate_limit_event
from .retry import RetryAttemptMetadata, RetryPolicy, call_with_retries
from .text_annotation_polling import (
    TRANSIENT_TEXT_ANNOTATION_STATUS_CODES,
    poll_text_annotation_until_ready,
)


def _retry_metadata_payload(metadata: RetryAttemptMetadata) -> dict[str, Any]:
    return {
        "attempt_count": metadata.attempt_count,
        "last_status_code": metadata.last_status_code,
        "retry_after_ms": metadata.retry_after_ms,
        "backoff_ms": metadata.backoff_ms,
        "terminal_reason": metadata.terminal_reason,
    }


def _text_annotation_session_id(response: dict[str, Any]) -> str:
    candidate = response.get("id", response.get("content", ""))
    if isinstance(candidate, bytes):
        candidate = candidate.decode("utf-8", errors="replace")
    return str(candidate).strip()


class RateLimiter:
    """Token bucket rate limiter for API requests."""

    def __init__(self, rate: float, burst: int = 1):
        """Initialize rate limiter.

        Args:
            rate: Requests per second
            burst: Maximum burst size
        """
        self.rate = rate
        self.burst = float(burst)
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """Acquire a token, blocking until one is available.

        The token is consumed before this method returns. The return value is
        the cumulative wait time spent inside this call (0.0 if no wait was
        required), which callers may log for telemetry. Callers MUST NOT sleep
        again on the returned value -- the wait has already happened.
        """
        total_wait = 0.0
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_update = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return total_wait
                wait = (1 - self.tokens) / self.rate
            await asyncio.sleep(wait)
            total_wait += wait


class PubTatorAPIError(Exception):
    """Custom exception for PubTator API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_data: dict[str, Any] | None = None,
        retry_metadata: dict[str, Any] | None = None,
        terminal_reason: str | None = None,
    ):
        """Initialize PubTator API error.

        Args:
            message: Error message
            status_code: HTTP status code
            response_data: Response data from API
            retry_metadata: Retry metadata sidecar
            terminal_reason: Stable terminal failure reason, when available
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data
        self.retry_metadata = retry_metadata or {}
        self.terminal_reason = terminal_reason


class PubTator3Client:
    """Async HTTP client for PubTator3 API with rate limiting."""

    def __init__(
        self,
        config: APIConfig = api_config,
        text_config: TextProcessingConfig = text_processing_config,
        logger: FilteringBoundLogger | None = None,
    ):
        """Initialize PubTator3 API client.

        Args:
            config: API configuration
            text_config: Text processing configuration
            logger: Optional logger instance
        """
        self.config = config
        self.text_config = text_config
        self.logger = logger

        # Rate limiter based on API guidelines (max 3 requests/second)
        self.rate_limiter = RateLimiter(rate=config.rate_limit_per_second)

        # HTTP client with appropriate headers
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={
                "User-Agent": "PubTator-Link/1.0.0 (https://github.com/ai-assistant/pubtator-link)",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

        # Text processing client (different endpoint)
        self.text_client = httpx.AsyncClient(
            timeout=httpx.Timeout(text_config.timeout),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={
                "User-Agent": "PubTator-Link/1.0.0 (https://github.com/ai-assistant/pubtator-link)",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    async def close(self) -> None:
        """Close HTTP clients."""
        await self.client.aclose()
        await self.text_client.aclose()

    async def __aenter__(self) -> "PubTator3Client":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def _make_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        use_text_client: bool = False,
        retry: bool = True,
    ) -> dict[str, Any]:
        """Make rate-limited HTTP request.

        Args:
            method: HTTP method
            url: Request URL
            params: Query parameters
            data: Form data for POST requests
            use_text_client: Use text processing client
            retry: Retry transient failures for idempotent requests

        Returns:
            Response data

        Raises:
            PubTatorAPIError: On API errors
        """
        response_data, _retry_metadata = await self._make_request_with_metadata(
            method,
            url,
            params=params,
            data=data,
            use_text_client=use_text_client,
            retry=retry,
        )
        return response_data

    def _cap_for_content_type(self, content_type: str) -> int:
        if "application/pdf" in content_type.lower():
            return self.config.pdf_max_bytes
        return self.config.text_max_bytes

    async def _make_request_with_metadata(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        use_text_client: bool = False,
        retry: bool = True,
    ) -> tuple[dict[str, Any], RetryAttemptMetadata]:
        """Make rate-limited HTTP request and return retry metadata sidecar."""
        # Apply rate limiting (blocks until a token is available)
        wait_time = await self.rate_limiter.acquire()
        if wait_time > 0 and self.logger:
            log_rate_limit_event(self.logger, endpoint=url, wait_time=wait_time)

        client = self.text_client if use_text_client else self.client
        start_time = time.time()
        retry_metadata = RetryAttemptMetadata(attempt_count=1)

        try:
            method_upper = method.upper()
            if method_upper not in {"GET", "POST"}:
                raise ValueError(f"Unsupported HTTP method: {method}")

            def raise_payload_too_large(
                response: httpx.Response,
                max_bytes: int,
            ) -> None:
                nonlocal retry_metadata
                retry_metadata = RetryAttemptMetadata(
                    attempt_count=retry_metadata.attempt_count,
                    last_status_code=response.status_code,
                    retry_after_ms=retry_metadata.retry_after_ms,
                    backoff_ms=retry_metadata.backoff_ms,
                    terminal_reason="payload_too_large",
                )
                payload = _retry_metadata_payload(retry_metadata)
                raise PubTatorAPIError(
                    f"Response body exceeds {max_bytes} byte limit",
                    status_code=response.status_code,
                    response_data={"retry_metadata": payload},
                    retry_metadata=payload,
                    terminal_reason="payload_too_large",
                )

            async def send() -> httpx.Response:
                stream_kwargs: dict[str, Any] = {"params": params}
                if method_upper == "POST":
                    stream_kwargs["data"] = data

                async with client.stream(method_upper, url, **stream_kwargs) as response:
                    content_type = response.headers.get("content-type", "").lower()
                    max_bytes = self._cap_for_content_type(content_type)
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            if int(content_length) > max_bytes:
                                raise_payload_too_large(response, max_bytes)
                        except ValueError:
                            pass

                    body_parts: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise_payload_too_large(response, max_bytes)
                        body_parts.append(chunk)

                    headers = httpx.Headers(response.headers)
                    headers.pop("content-encoding", None)
                    headers.pop("content-length", None)
                    return httpx.Response(
                        response.status_code,
                        headers=headers,
                        content=b"".join(body_parts),
                        request=response.request,
                        extensions=response.extensions,
                    )

            if retry and (method_upper == "GET" or use_text_client):
                policy = RetryPolicy()
                try:
                    response, retry_metadata = await call_with_retries(
                        send,
                        policy=policy,
                    )
                except httpx.RequestError as exc:
                    retry_metadata = RetryAttemptMetadata(
                        attempt_count=policy.max_attempts,
                        terminal_reason="request_error",
                    )
                    raise PubTatorAPIError(
                        f"Request failed: {exc!s}",
                        response_data={"retry_metadata": _retry_metadata_payload(retry_metadata)},
                        retry_metadata=_retry_metadata_payload(retry_metadata),
                    ) from exc
            else:
                try:
                    response = await send()
                except httpx.RequestError as exc:
                    retry_metadata = RetryAttemptMetadata(
                        attempt_count=1,
                        terminal_reason="request_error",
                    )
                    raise PubTatorAPIError(
                        f"Request failed: {exc!s}",
                        response_data={"retry_metadata": _retry_metadata_payload(retry_metadata)},
                        retry_metadata=_retry_metadata_payload(retry_metadata),
                    ) from exc
                retry_metadata = RetryAttemptMetadata(
                    attempt_count=1,
                    last_status_code=response.status_code,
                )

            response_time = time.time() - start_time

            if self.logger:
                log_api_request(
                    self.logger,
                    method=method_upper,
                    url=str(response.url),
                    response_time=response_time,
                    status_code=response.status_code,
                )

            response.raise_for_status()

            # Handle different response types
            content_type = response.headers.get("content-type", "").lower()
            body = response.content
            if "application/json" in content_type:
                return json.loads(body.decode("utf-8")), retry_metadata
            elif (
                "text/plain" in content_type
                or "text/html" in content_type
                or "application/xml" in content_type
            ):
                return (
                    {
                        "content": body.decode(response.encoding or "utf-8", errors="replace"),
                        "content_type": content_type,
                    },
                    retry_metadata,
                )
            else:
                return (
                    {"content": response.content, "content_type": content_type},
                    retry_metadata,
                )

        except httpx.HTTPStatusError as e:
            # Sever the (caller-influenceable) raw upstream body: surface only the
            # safe HTTP-status scalar, never the body (message/response_data/logs).
            status_code = e.response.status_code
            body_lowered = e.response.text.lower()
            updating = (
                "currently updating the database" in body_lowered
                or "please try again later" in body_lowered
            )
            retry_payload = _retry_metadata_payload(retry_metadata)
            raise PubTatorAPIError(
                f"PubTator3 API returned HTTP {status_code}.",
                status_code=status_code,
                response_data={"retry_metadata": retry_payload},
                retry_metadata=retry_payload,
                terminal_reason="filtered_search_unavailable" if updating else None,
            ) from e

    async def export_publications(
        self, pmids: list[str], format: str = "biocjson", full: bool = False
    ) -> dict[str, Any]:
        """Export publication annotations.

        Args:
            pmids: List of PubMed IDs
            format: Export format (pubtator, biocxml, biocjson)
            full: Include full text (biocxml/biocjson only)

        Returns:
            Export data
        """
        response_data, _retry_metadata = await self.export_publications_with_metadata(
            pmids,
            format=format,
            full=full,
        )
        return response_data

    async def export_publications_with_metadata(
        self, pmids: list[str], format: str = "biocjson", full: bool = False
    ) -> tuple[dict[str, Any], RetryAttemptMetadata]:
        """Export publication annotations with retry metadata sidecar."""
        if format not in self.config.export_formats:
            raise ValueError(f"Unsupported format: {format}")

        if full and format == "pubtator":
            raise ValueError("Full text not supported for pubtator format")

        url = f"{self.config.base_url}/publications/export/{format}"
        params = {"pmids": ",".join(pmids)}

        if full:
            params["full"] = "true"

        return await self._make_request_with_metadata("GET", url, params=params)

    async def export_pmc_publications(
        self, pmcids: list[str], format: str = "biocjson"
    ) -> dict[str, Any]:
        """Export PMC publication annotations.

        Args:
            pmcids: List of PMC IDs
            format: Export format (biocxml, biocjson)

        Returns:
            Export data
        """
        if format not in ["biocxml", "biocjson"]:
            raise ValueError(f"PMC export only supports biocxml/biocjson, got: {format}")

        url = f"{self.config.base_url}/publications/pmc_export/{format}"
        params = {"pmcids": ",".join(pmcids)}

        return await self._make_request("GET", url, params=params)

    async def autocomplete_entity(
        self, query: str, concept: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        """Find entity ID through autocomplete.

        Args:
            query: Search query
            concept: Bioconcept type filter
            limit: Maximum results

        Returns:
            Autocomplete results
        """
        url = f"{self.config.base_url}/entity/autocomplete/"
        params = {"query": query, "limit": limit}

        if concept:
            if concept not in self.config.bioconcept_types:
                raise ValueError(f"Unsupported bioconcept: {concept}")
            params["concept"] = concept

        return await self._make_request("GET", url, params=params)

    async def search_publications(
        self,
        text: str,
        page: int = 1,
        sort: str | None = None,
        filters: str | None = None,
        sections: str | None = None,
    ) -> dict[str, Any]:
        """Search for publications with advanced filtering.

        Args:
            text: Search query (free text, entity ID, or relation)
            page: Page number for pagination
            sort: Sort order. PubTator3 accepts only "score desc", "date desc",
                or "_id desc" (descending only); other values return HTTP 400.
            filters: JSON string with advanced filters (type, journal, author, year)
            sections: Comma-separated list of sections to search within

        Returns:
            Search results with publications matching criteria

        Example:
            # Basic search
            await client.search_publications("breast cancer")

            # Advanced search with filters
            filters = '{"type":["Review"],"journal":["Nature"],"year":{"min":2020}}'
            await client.search_publications(
                text="BRCA1 mutations",
                filters=filters,
                sections="title,abstract"
            )
        """
        url = f"{self.config.base_url}/search/"
        params = {"text": text, "page": page}

        if sort is not None:
            params["sort"] = sort
        if filters is not None and filters.strip():
            params["filters"] = filters
        if sections is not None and sections.strip():
            params["sections"] = sections

        return await self._make_request("GET", url, params=params)

    async def find_relations(
        self, e1: str, relation_type: str | None = None, e2: str | None = None
    ) -> dict[str, Any]:
        """Find related entities.

        Args:
            e1: Primary entity ID
            relation_type: Relation type filter
            e2: Target entity type filter

        Returns:
            Related entities
        """
        if not e1.startswith("@"):
            raise ValueError("Entity ID must start with '@'")

        url = f"{self.config.base_url}/relations"
        params = {"e1": e1}

        if relation_type:
            if relation_type not in self.config.relation_types:
                raise ValueError(f"Unsupported relation type: {relation_type}")
            params["type"] = relation_type

        if e2:
            if e2 not in self.config.bioconcept_types:
                raise ValueError(f"Unsupported entity type: {e2}")
            params["e2"] = e2

        return await self._make_request("GET", url, params=params)

    async def submit_text_annotation(self, text: str, bioconcept: str = "Gene") -> str:
        """Submit text for annotation processing.

        Args:
            text: Text to annotate
            bioconcept: Bioconcept type to extract

        Returns:
            Session ID for result retrieval
        """
        if bioconcept not in self.text_config.supported_bioconcepts:
            raise ValueError(f"Unsupported bioconcept: {bioconcept}")

        url = f"{self.text_config.base_url}/request.cgi"
        data = {"text": text, "bioconcept": bioconcept}

        response = await self._make_request(
            "POST",
            url,
            data=data,
            use_text_client=True,
            retry=False,
        )

        session_id = _text_annotation_session_id(response)
        if not session_id:
            raise PubTatorAPIError("Failed to get session ID")

        return session_id

    async def retrieve_text_annotation(self, session_id: str) -> dict[str, Any]:
        """Retrieve text annotation results.

        Args:
            session_id: Session ID from submission

        Returns:
            Annotation results or status
        """
        url = f"{self.text_config.base_url}/retrieve.cgi"
        data = {"id": session_id}

        return await self._make_request(
            "POST",
            url,
            data=data,
            use_text_client=True,
            retry=True,
        )

    async def retrieve_text_annotation_until_ready(
        self, session_id: str, timeout_ms: int = 30000
    ) -> dict[str, Any] | None:
        """Poll text annotation results until ready or timeout."""
        return await poll_text_annotation_until_ready(
            self.retrieve_text_annotation,
            session_id=session_id,
            timeout_ms=timeout_ms,
            is_transient_error=lambda exc: (
                isinstance(exc, PubTatorAPIError)
                and exc.status_code in TRANSIENT_TEXT_ANNOTATION_STATUS_CODES
            ),
        )

    async def get_annotation_results(self, session_id: str) -> dict[str, Any]:
        """Alias for retrieve_text_annotation to match test expectations.

        Args:
            session_id: Session ID from submission

        Returns:
            Annotation results or status
        """
        return await self.retrieve_text_annotation(session_id)
