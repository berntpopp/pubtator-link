"""Configuration management for PubTator-Link server."""

import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
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

    # Server configuration
    transport: Literal["unified", "http", "stdio"] = Field(
        default="unified", description="Server transport mode"
    )
    host: str = Field(default="127.0.0.1", description="Server host")
    port: int = Field(default=8000, description="Server port")
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path")

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
    cors_origins: list[str] = Field(
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

    # Logging configuration
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: Literal["json", "console"] = Field(default="console", description="Log format")

    # Feature flags
    enable_docs: bool = Field(default=True, description="Enable API documentation")
    enable_cache_endpoints: bool = Field(
        default=True, description="Enable cache management endpoints"
    )
    mcp_profile: Literal["lean", "full", "readonly"] = Field(
        default="lean", description="MCP tool registration profile"
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
    enable_docling: bool = Field(default=False, description="Enable Docling PDF fallback")
    enable_europe_pmc_fallback: bool = Field(
        default=False,
        description="Enable opt-in Europe PMC open-access fallback for review preparation",
    )
    europe_pmc_base_url: str = Field(default="https://www.ebi.ac.uk/europepmc/webservices/rest")
    europe_pmc_rate_limit_per_second: float = Field(default=1.0, gt=0, le=5)
    europe_pmc_timeout_seconds: int = Field(default=20, ge=2, le=120)
    europe_pmc_max_concurrency: int = Field(default=1, ge=1, le=5)

    @field_validator("mcp_path")
    @classmethod
    def validate_mcp_path(cls, v: str) -> str:
        """Ensure MCP path starts with forward slash."""
        if not v.startswith("/"):
            return f"/{v}"
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v  # type: ignore[no-any-return]

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


@dataclass
class APIConfig:
    """PubTator3 API configuration."""

    base_url: str
    timeout: int
    rate_limit_per_second: float

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
        )


# Global settings instance
settings = ServerSettings()

# Configuration instances
api_config = APIConfig(
    base_url=settings.api_base_url,
    timeout=settings.api_timeout,
    rate_limit_per_second=settings.rate_limit_per_second,
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
