"""PubTator3 API client with rate limiting and error handling."""

import asyncio
import time
from typing import Any

import httpx
from structlog.typing import FilteringBoundLogger

from ..config import APIConfig, TextProcessingConfig, api_config, text_processing_config
from ..logging_config import log_api_request, log_rate_limit_event
from .retry import RetryPolicy, call_with_retries


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
    ):
        """Initialize PubTator API error.

        Args:
            message: Error message
            status_code: HTTP status code
            response_data: Response data from API
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


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
            headers={
                "User-Agent": "PubTator-Link/1.0.0 (https://github.com/ai-assistant/pubtator-link)",
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

        # Text processing client (different endpoint)
        self.text_client = httpx.AsyncClient(
            timeout=httpx.Timeout(text_config.timeout),
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
        # Apply rate limiting (blocks until a token is available)
        wait_time = await self.rate_limiter.acquire()
        if wait_time > 0 and self.logger:
            log_rate_limit_event(self.logger, endpoint=url, wait_time=wait_time)

        client = self.text_client if use_text_client else self.client
        start_time = time.time()

        try:
            method_upper = method.upper()
            if method_upper not in {"GET", "POST"}:
                raise ValueError(f"Unsupported HTTP method: {method}")

            async def send() -> httpx.Response:
                if method_upper == "GET":
                    return await client.get(url, params=params)
                return await client.post(url, params=params, data=data)

            if retry and method_upper == "GET":
                response, _retry_metadata = await call_with_retries(
                    send,
                    policy=RetryPolicy(),
                )
            else:
                response = await send()

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
            if "application/json" in content_type:
                return response.json()  # type: ignore[no-any-return]
            elif (
                "text/plain" in content_type
                or "text/html" in content_type
                or "application/xml" in content_type
            ):
                return {"content": response.text, "content_type": content_type}
            else:
                return {"content": response.content, "content_type": content_type}

        except httpx.HTTPStatusError as e:
            error_data = None
            try:
                error_data = e.response.json()
            except Exception:
                if self.logger:
                    self.logger.warning("Failed to parse error response as JSON")

            raise PubTatorAPIError(
                f"HTTP {e.response.status_code}: {e.response.text}",
                status_code=e.response.status_code,
                response_data=error_data,
            ) from e
        except httpx.RequestError as e:
            raise PubTatorAPIError(f"Request failed: {e!s}") from e

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
        if format not in self.config.export_formats:
            raise ValueError(f"Unsupported format: {format}")

        if full and format == "pubtator":
            raise ValueError("Full text not supported for pubtator format")

        url = f"{self.config.base_url}/publications/export/{format}"
        params = {"pmids": ",".join(pmids)}

        if full:
            params["full"] = "true"

        return await self._make_request("GET", url, params=params)

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
            sort: Sort order ("date desc", "date asc", "score desc", "score asc")
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

        # Extract session ID from response
        session_id = str(response.get("content", "")).strip()
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
            retry=False,
        )

    async def get_annotation_results(self, session_id: str) -> dict[str, Any]:
        """Alias for retrieve_text_annotation to match test expectations.

        Args:
            session_id: Session ID from submission

        Returns:
            Annotation results or status
        """
        return await self.retrieve_text_annotation(session_id)
