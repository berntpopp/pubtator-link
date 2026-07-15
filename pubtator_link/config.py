"""Configuration management for PubTator-Link server."""

import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ServerSettings(BaseSettings):
    """Server configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PUBTATOR_LINK_",
        case_sensitive=False,
        extra="ignore",
    )

    # Server configuration (Streamable HTTP only; stdio is not supported)
    transport: Literal["unified", "http"] = Field(
        default="unified", description="Server transport mode"
    )
    host: str = Field(default="127.0.0.1", description="Server host")
    port: int = Field(default=8000, description="Server port")
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path")
    # NoDecode: pydantic-settings JSON-decodes complex fields inside the env source,
    # which raises SettingsError on a CSV value before `parse_origin_allowlists`
    # (mode="before") ever runs — so the CSV support that validator advertises was
    # unreachable from the environment, and `cp .env.example .env` failed to load.
    # Deferring the decode to the validator makes both spellings work: CSV (as
    # .env.example writes them) and JSON (as docker-compose.yml writes them).
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"],
        description="Exact Host header allowlist for inbound HTTP requests",
    )
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Exact Origin header allowlist; requests without Origin remain allowed",
    )

    # API configuration
    api_base_url: str = Field(
        default="https://www.ncbi.nlm.nih.gov/research/pubtator3-api",
        description="PubTator3 API base URL",
    )
    api_timeout: int = Field(default=30, description="API request timeout in seconds")
    rate_limit_per_second: float = Field(
        default=2.5,
        description="Rate limit for API requests (max 3/sec per PubTator3 guidelines)",
    )

    # Text processing API
    text_api_base_url: str = Field(
        default="https://www.ncbi.nlm.nih.gov/CBBresearch/Lu/Demo/RESTful",
        description="Text processing API base URL",
    )
    text_api_timeout: int = Field(default=60, description="Text processing timeout in seconds")

    # Cache configuration
    cache_size: int = Field(default=1000, description="LRU cache size")
    cache_ttl: int = Field(default=3600, description="Cache TTL in seconds")

    # CORS configuration
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
        description="CORS allowed origins",
    )
    cors_allow_methods: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["GET", "POST", "OPTIONS"],
        description="CORS allowed HTTP methods",
    )
    cors_allow_headers: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "Authorization",
            "Content-Type",
            "Mcp-Session-Id",
            "MCP-Protocol-Version",
            "Last-Event-ID",
            "X-Request-ID",
        ],
        description="CORS allowed request headers",
    )
    http_max_request_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        description="Maximum inbound HTTP request body size in bytes",
    )
    enable_inbound_rate_limit: bool = Field(
        default=False,
        description="Enable simple per-client inbound HTTP rate limiting",
    )
    inbound_rate_limit_per_minute: int = Field(
        default=120,
        ge=1,
        description="Maximum requests per client per minute when inbound rate limiting is enabled",
    )
    review_export_base_dir: str | None = Field(
        default=None,
        description=(
            "Base directory for server-generated export_review_audit_bundle files. "
            "Unset disables file export; inline/compact responses still work."
        ),
    )
    trust_proxy_headers: bool = Field(
        default=False,
        description=(
            "Trust the rightmost X-Forwarded-For entry (added by a known reverse proxy) "
            "for inbound rate limiting. Leave False when directly reachable."
        ),
    )

    # Logging configuration
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: Literal["json", "console"] = Field(default="console", description="Log format")

    # Feature flags
    enable_docs: bool = Field(default=True, description="Enable API documentation")
    enable_cache_endpoints: bool = Field(
        default=False, description="Enable opt-in cache management endpoints"
    )
    mcp_profile: Literal["lean", "full", "readonly"] = Field(
        default="readonly", description="MCP tool registration profile"
    )
    mcp_service_token: str | None = Field(
        default=None, description="Router-owned bearer token required by /mcp"
    )
    allow_unauthenticated_writes: bool = Field(
        default=False,
        description="Explicit loopback-development exception for write-capable profiles",
    )

    # --- Edge auth (AUTH_MODE=none keeps today's behavior; oauth adds Keycloak) ---
    auth_mode: Literal["none", "oauth"] = Field(
        default="none",
        description="Edge auth for /mcp: none (open/token) or oauth (Keycloak + service token)",
    )
    oauth_authorize_url: str | None = Field(default=None)
    oauth_token_url: str | None = Field(default=None)
    oauth_client_id: str | None = Field(default=None)
    oauth_client_secret: str | None = Field(default=None)
    oauth_jwt_signing_key: str | None = Field(
        default=None,
        description="Fixed key so OAuthProxy tokens/client store survive restarts + KC secret rotation",
    )
    oauth_allowed_client_redirect_uris: list[str] = Field(
        default_factory=list,
        description="Downstream MCP-client redirect URI patterns (claude.ai + approved loopback)",
    )
    jwt_issuer: str | None = Field(default=None)
    jwt_jwks_url: str | None = Field(default=None)
    jwt_audience: str | None = Field(
        default=None,
        description="Token audience == PubTator resource URI (MUST for a protected resource)",
    )
    public_base_url: str | None = Field(
        default=None,
        description="Public ROOT origin (PRM/resource base); bare origin, no path — avoids /mcp/mcp",
    )
    require_write_scope: bool = Field(
        default=False,
        description="When true, write tools require the pubtator:write scope",
    )

    def validate_oauth_config(self) -> None:
        """Fail fast if oauth mode is missing/misconfigured. No-op in none mode."""
        if self.auth_mode != "oauth":
            return
        required = {
            "PUBTATOR_LINK_OAUTH_AUTHORIZE_URL": self.oauth_authorize_url,
            "PUBTATOR_LINK_OAUTH_TOKEN_URL": self.oauth_token_url,
            "PUBTATOR_LINK_OAUTH_CLIENT_ID": self.oauth_client_id,
            "PUBTATOR_LINK_OAUTH_CLIENT_SECRET": self.oauth_client_secret,
            "PUBTATOR_LINK_OAUTH_JWT_SIGNING_KEY": self.oauth_jwt_signing_key,
            "PUBTATOR_LINK_JWT_ISSUER": self.jwt_issuer,
            "PUBTATOR_LINK_JWT_JWKS_URL": self.jwt_jwks_url,
            "PUBTATOR_LINK_JWT_AUDIENCE": self.jwt_audience,
            "PUBTATOR_LINK_PUBLIC_BASE_URL": self.public_base_url,
            # Required so the router verifier is present and token signing is stable.
            "PUBTATOR_LINK_MCP_SERVICE_TOKEN": self.mcp_service_token,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"oauth mode requires: {', '.join(missing)}")

        from urllib.parse import urlsplit

        assert self.public_base_url is not None  # narrowed by the missing-check
        parts = urlsplit(self.public_base_url)
        if (
            parts.scheme != "https"
            or not parts.netloc
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError(
                "PUBTATOR_LINK_PUBLIC_BASE_URL must be a bare https origin "
                "(no path/query/fragment) so the advertised resource is not doubled"
            )
        expected_audience = self.public_base_url.rstrip("/") + self.mcp_path
        if self.jwt_audience != expected_audience:
            raise ValueError(
                "PUBTATOR_LINK_JWT_AUDIENCE must equal PUBLIC_BASE_URL + mcp_path "
                f"({expected_audience})"
            )

    # Review-scoped re-RAG POC
    database_url: str | None = Field(default=None, description="PostgreSQL database URL")
    auto_migrate: bool = Field(
        default=False,
        description="Apply bundled PostgreSQL migrations automatically during startup",
    )
    require_schema_current: bool = Field(
        default=False,
        description="Fail startup when review PostgreSQL schema is not current",
    )
    review_prep_concurrency: int = Field(
        default=2, ge=1, le=8, description="Concurrent review evidence preparation jobs"
    )
    review_prep_document_timeout_seconds: int = Field(
        default=60, ge=5, le=600, description="Per-document preparation timeout"
    )
    review_prep_source_timeout_seconds: int = Field(
        default=20, ge=2, le=120, description="Per-source retrieval timeout"
    )
    review_retrieval_concurrency: int = Field(
        default=4, ge=1, le=10, description="Concurrent review context retrieval queries"
    )
    review_preflight_concurrency: int = Field(
        default=3, ge=1, le=10, description="Concurrent review source preflight probes"
    )
    review_index_ttl_seconds: int | None = Field(
        default=None,
        ge=60,
        description="Optional TTL for stale review indexes; disabled when unset",
    )
    enable_review_index_delete: bool = Field(
        default=False,
        description="Enable destructive review index deletion for private deployments",
    )
    enable_review_index_cleanup_endpoint: bool = Field(
        default=False,
        description="Enable manual review index cleanup endpoint for private deployments",
    )
    review_prep_pdf_max_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024, description="Maximum downloaded PDF bytes"
    )
    review_prep_text_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1024,
        description="Maximum downloaded text/XML/HTML bytes",
    )
    allow_http_urls: bool = Field(
        default=False, description="Allow http URLs for local curated URL development"
    )
    review_prep_curated_url_host_allowlist: list[str] = Field(
        default_factory=lambda: [
            "ncbi.nlm.nih.gov",
            "www.ncbi.nlm.nih.gov",
            "europepmc.org",
            "www.ebi.ac.uk",
            "api.openalex.org",
            "api.crossref.org",
        ],
        description=(
            "Suffix-match hostnames allowed for index_review_evidence "
            "curated_urls. Empty list means no curated URLs accepted."
        ),
    )
    enable_docling: bool = Field(default=False, description="Enable Docling PDF fallback")
    enable_europe_pmc_fallback: bool = Field(
        default=False,
        description="Enable opt-in Europe PMC open-access fallback for review preparation",
    )
    europe_pmc_base_url: str = Field(default="https://www.ebi.ac.uk/europepmc/webservices/rest")
    europe_pmc_rate_limit_per_second: float = Field(default=1.0, gt=0, le=5)
    europe_pmc_timeout_seconds: int = Field(default=20, ge=2, le=120)
    europe_pmc_max_concurrency: int = Field(default=1, ge=1, le=5)
    crossref_mailto: str | None = Field(
        default=None, description="Optional Crossref polite-pool mailto"
    )
    openalex_mailto: str | None = Field(
        default=None, description="Optional OpenAlex polite-pool mailto"
    )
    unpaywall_email: str | None = Field(
        default=None, description="Required email for optional Unpaywall API use"
    )
    review_embedding_rerank_enabled: bool = False
    review_embedding_model: str = "BAAI/bge-small-en-v1.5"
    review_embedding_dim: int = Field(default=384, ge=1, le=2000)
    review_embedding_top_k: int = Field(default=50, ge=1, le=100)
    review_embedding_rrf_k: int = Field(default=60, ge=1, le=1000)
    review_embedding_batch_size: int = Field(default=32, ge=1, le=256)
    review_embedding_device: str = "auto"

    @field_validator("mcp_path")
    @classmethod
    def validate_mcp_path(cls, v: str) -> str:
        """Ensure MCP path starts with forward slash."""
        if not v.startswith("/"):
            return f"/{v}"
        return v

    @field_validator("allowed_hosts", "allowed_origins", "cors_origins", mode="before")
    @classmethod
    def parse_origin_allowlists(cls, v: Any) -> list[str]:
        """Parse exact host/origin allowlists from JSON, CSV, or lists."""
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                loaded = json.loads(stripped)
                if isinstance(loaded, list):
                    return [str(item).strip() for item in loaded if str(item).strip()]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v  # type: ignore[no-any-return]

    @field_validator("allowed_hosts")
    @classmethod
    def reject_host_wildcards(cls, hosts: list[str]) -> list[str]:
        if any(marker in host for host in hosts for marker in "*?[]"):
            raise ValueError("allowed_hosts entries must be exact; wildcard syntax is forbidden")
        return hosts

    @field_validator("cors_allow_methods", "cors_allow_headers", mode="before")
    @classmethod
    def parse_csv_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                loaded = json.loads(stripped)
                if isinstance(loaded, list):
                    return [str(item).strip() for item in loaded if str(item).strip()]
            return [item.strip() for item in v.split(",") if item.strip()]
        return v  # type: ignore[no-any-return]

    @model_validator(mode="after")
    def validate_write_boundary(self) -> "ServerSettings":
        self.validate_write_boundary_for_host(self.host)
        return self

    def validate_write_boundary_for_host(self, host: str) -> None:
        """Validate service authentication against the effective runtime bind."""
        local_exception = self.allow_unauthenticated_writes and host in {
            "127.0.0.1",
            "::1",
            "localhost",
        }
        if self.allow_unauthenticated_writes and not local_exception:
            raise ValueError("unauthenticated writes are restricted to a loopback bind")
        if self.mcp_profile != "readonly" and not self.mcp_service_token and not local_exception:
            raise ValueError(
                "write-capable MCP profile requires PUBTATOR_LINK_MCP_SERVICE_TOKEN "
                "or the explicit loopback-development exception"
            )


@dataclass
class APIConfig:
    """PubTator3 API configuration."""

    base_url: str
    timeout: int
    rate_limit_per_second: float
    text_max_bytes: int = 5 * 1024 * 1024
    pdf_max_bytes: int = 20 * 1024 * 1024

    # Supported formats
    export_formats: list[str] = field(default_factory=lambda: ["pubtator", "biocxml", "biocjson"])

    # Bioconcept types
    bioconcept_types: list[str] = field(
        default_factory=lambda: [
            "Gene",
            "Disease",
            "Chemical",
            "Species",
            "Variant",
            "CellLine",
            "Phenotype",
        ]
    )

    # Relation types
    relation_types: list[str] = field(
        default_factory=lambda: [
            "treat",
            "cause",
            "cotreat",
            "convert",
            "compare",
            "interact",
            "associate",
            "positive_correlate",
            "negative_correlate",
            "prevent",
            "inhibit",
            "stimulate",
            "drug_interact",
        ]
    )


@dataclass
class TextProcessingConfig:
    """Text processing API configuration."""

    base_url: str
    timeout: int

    # Available bioconcepts for text processing
    supported_bioconcepts: list[str] = field(
        default_factory=lambda: [
            "Gene",
            "Disease",
            "Chemical",
            "Species",
            "Variant",
            "CellLine",
        ]
    )


@dataclass
class CacheConfig:
    """Cache configuration."""

    size: int
    ttl: int

    # Cache keys for different operations
    keys: dict[str, str] = field(
        default_factory=lambda: {
            "publication_export": "pub_export:{pmids}:{format}:{full}",
            "pmc_export": "pmc_export:{pmcids}:{format}",
            "entity_autocomplete": "entity_ac:{query}:{concept}:{limit}",
            "search": "search:{text}:{page}",
            "relations": "relations:{e1}:{type}:{e2}",
            "text_processing": "text_proc:{session_id}",
        }
    )


@dataclass(frozen=True)
class ReviewReragConfig:
    """Review-scoped re-RAG POC configuration."""

    database_url: str | None
    prep_concurrency: int
    document_timeout_seconds: int
    source_timeout_seconds: int
    pdf_max_bytes: int
    text_max_bytes: int
    allow_http_urls: bool
    enable_docling: bool
    curated_url_host_allowlist: tuple[str, ...] = field(default_factory=tuple)
    auto_migrate: bool = False
    require_schema_current: bool = False
    retrieval_concurrency: int = 4
    preflight_concurrency: int = 3
    index_ttl_seconds: int | None = None
    enable_index_delete: bool = False
    enable_index_cleanup_endpoint: bool = False
    enable_europe_pmc_fallback: bool = False
    europe_pmc_base_url: str = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    europe_pmc_rate_limit_per_second: float = 1.0
    europe_pmc_timeout_seconds: int = 20
    europe_pmc_max_concurrency: int = 1
    embedding_rerank_enabled: bool = False
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_top_k: int = 50
    embedding_rrf_k: int = 60
    embedding_batch_size: int = 32
    embedding_device: str = "auto"

    @classmethod
    def from_settings(cls, server_settings: ServerSettings) -> "ReviewReragConfig":
        return cls(
            database_url=server_settings.database_url,
            auto_migrate=server_settings.auto_migrate,
            require_schema_current=server_settings.require_schema_current,
            prep_concurrency=server_settings.review_prep_concurrency,
            document_timeout_seconds=server_settings.review_prep_document_timeout_seconds,
            source_timeout_seconds=server_settings.review_prep_source_timeout_seconds,
            pdf_max_bytes=server_settings.review_prep_pdf_max_bytes,
            text_max_bytes=server_settings.review_prep_text_max_bytes,
            allow_http_urls=server_settings.allow_http_urls,
            enable_docling=server_settings.enable_docling,
            curated_url_host_allowlist=tuple(
                server_settings.review_prep_curated_url_host_allowlist
            ),
            retrieval_concurrency=server_settings.review_retrieval_concurrency,
            preflight_concurrency=server_settings.review_preflight_concurrency,
            index_ttl_seconds=server_settings.review_index_ttl_seconds,
            enable_index_delete=server_settings.enable_review_index_delete,
            enable_index_cleanup_endpoint=server_settings.enable_review_index_cleanup_endpoint,
            enable_europe_pmc_fallback=server_settings.enable_europe_pmc_fallback,
            europe_pmc_base_url=server_settings.europe_pmc_base_url,
            europe_pmc_rate_limit_per_second=server_settings.europe_pmc_rate_limit_per_second,
            europe_pmc_timeout_seconds=server_settings.europe_pmc_timeout_seconds,
            europe_pmc_max_concurrency=server_settings.europe_pmc_max_concurrency,
            embedding_rerank_enabled=server_settings.review_embedding_rerank_enabled,
            embedding_model=server_settings.review_embedding_model,
            embedding_dim=server_settings.review_embedding_dim,
            embedding_top_k=server_settings.review_embedding_top_k,
            embedding_rrf_k=server_settings.review_embedding_rrf_k,
            embedding_batch_size=server_settings.review_embedding_batch_size,
            embedding_device=server_settings.review_embedding_device,
        )


# Global settings instance
settings = ServerSettings()

# Configuration instances
api_config = APIConfig(
    base_url=settings.api_base_url,
    timeout=settings.api_timeout,
    rate_limit_per_second=settings.rate_limit_per_second,
    text_max_bytes=settings.review_prep_text_max_bytes,
    pdf_max_bytes=settings.review_prep_pdf_max_bytes,
)

text_processing_config = TextProcessingConfig(
    base_url=settings.text_api_base_url,
    timeout=settings.text_api_timeout,
)

cache_config = CacheConfig(
    size=settings.cache_size,
    ttl=settings.cache_ttl,
)

review_rerag_config = ReviewReragConfig.from_settings(settings)
