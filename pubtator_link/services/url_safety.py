"""SSRF-safe URL fetching for curated review sources."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from typing import Any, ClassVar
from urllib.parse import urljoin, urlparse

import httpx

from pubtator_link.config import ReviewReragConfig


class UrlSafetyError(ValueError):
    """Raised when a URL is unsafe or cannot be fetched within safety limits."""


def enforce_host_allowlist(allowlist: tuple[str, ...], hostname: str) -> None:
    """Allow exact configured hosts or their subdomains."""
    normalized_hostname = hostname.lower().rstrip(".")
    normalized_allowlist = tuple(
        host.strip().lower().rstrip(".") for host in allowlist if host.strip()
    )

    for allowed_host in normalized_allowlist:
        if normalized_hostname == allowed_host or normalized_hostname.endswith(f".{allowed_host}"):
            return

    raise UrlSafetyError(f"Host '{hostname}' not in allowlist for curated_urls")


class SafeUrlFetcher:
    """Fetch curated source URLs with SSRF and response-size protections."""

    _REDIRECT_STATUSES: ClassVar[set[int]] = {301, 302, 303, 307, 308}
    _MAX_REDIRECTS = 3

    def __init__(self, config: ReviewReragConfig) -> None:
        self._config = config

    async def fetch(self, url: str) -> tuple[bytes, str]:
        next_url = url

        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(self._config.source_timeout_seconds),
            trust_env=False,
        ) as client:
            for _attempt in range(self._MAX_REDIRECTS + 1):
                self._validate_url(next_url)

                async with client.stream("GET", next_url) as response:
                    if response.status_code in self._REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise UrlSafetyError("Redirect response is missing Location header")
                        next_url = urljoin(next_url, location)
                        continue

                    if response.is_error:
                        raise UrlSafetyError(
                            f"Source fetch failed with HTTP {response.status_code}"
                        )

                    content_type = response.headers.get("content-type", "")
                    max_bytes = self._max_bytes_for(next_url, content_type)
                    self._validate_content_length(response.headers, max_bytes)
                    body = await self._read_with_cap(response, max_bytes)
                    return body, content_type

            raise UrlSafetyError("Too many redirects")

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise UrlSafetyError("Unsupported URL scheme")
        if parsed.scheme == "http" and not self._config.allow_http_urls:
            raise UrlSafetyError("HTTP URLs are disabled")
        if not parsed.hostname:
            raise UrlSafetyError("URL must include a hostname")

        enforce_host_allowlist(self._config.curated_url_host_allowlist, parsed.hostname)
        self._validate_resolved_addresses(parsed.hostname, parsed.port)

    def _validate_resolved_addresses(self, hostname: str, port: int | None) -> None:
        try:
            address_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UrlSafetyError("Could not resolve URL hostname") from exc

        addresses = self._extract_addresses(address_info)
        if not addresses:
            raise UrlSafetyError("Could not resolve URL hostname")

        for address in addresses:
            ip_address = ipaddress.ip_address(address)
            if self._is_unsafe_address(ip_address):
                raise UrlSafetyError(f"Resolved hostname to unsafe IP address: {ip_address}")

    @staticmethod
    def _extract_addresses(
        address_info: Iterable[tuple[Any, Any, Any, Any, tuple[Any, ...]]],
    ) -> set[str]:
        addresses: set[str] = set()
        for entry in address_info:
            sockaddr = entry[4]
            if sockaddr:
                addresses.add(str(sockaddr[0]))
        return addresses

    @staticmethod
    def _is_unsafe_address(ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return (
            not ip_address.is_global
            or ip_address.is_private
            or ip_address.is_loopback
            or ip_address.is_link_local
            or ip_address.is_multicast
            or ip_address.is_unspecified
            or ip_address.is_reserved
        )

    def _max_bytes_for(self, url: str, content_type: str) -> int:
        path = urlparse(url).path.lower()
        if "application/pdf" in content_type.lower() or path.endswith(".pdf"):
            return self._config.pdf_max_bytes
        return self._config.text_max_bytes

    @staticmethod
    def _validate_content_length(headers: httpx.Headers, max_bytes: int) -> None:
        content_length = headers.get("content-length")
        if content_length is None:
            return

        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise UrlSafetyError("Invalid Content-Length header") from exc

        if declared_size > max_bytes:
            raise UrlSafetyError("Content-Length exceeds configured byte cap")

    @staticmethod
    async def _read_with_cap(response: httpx.Response, max_bytes: int) -> bytes:
        chunks: list[bytes] = []
        total_size = 0

        async for chunk in response.aiter_bytes():
            total_size += len(chunk)
            if total_size > max_bytes:
                raise UrlSafetyError("Response body exceeds configured byte cap")
            chunks.append(chunk)

        return b"".join(chunks)
