"""Configuration management for PubTator-Link server."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    """Server configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
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

    # Logging configuration
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: Literal["json", "console"] = Field(default="console", description="Log format")

    # Feature flags
    enable_docs: bool = Field(default=True, description="Enable API documentation")
    enable_cache_endpoints: bool = Field(
        default=True, description="Enable cache management endpoints"
    )

    @field_validator("mcp_path")
    @classmethod
    def validate_mcp_path(cls, v: str) -> str:
        """Ensure MCP path starts with forward slash."""
        if not v.startswith("/"):
            return f"/{v}"
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


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
