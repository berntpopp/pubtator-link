from pubtator_link.config import ReviewReragConfig, ServerSettings


def test_review_rerag_config_defaults_are_fast_poc_values() -> None:
    settings = ServerSettings()
    config = ReviewReragConfig.from_settings(settings)

    assert config.database_url is None
    assert config.prep_concurrency == 2
    assert config.document_timeout_seconds == 60
    assert config.source_timeout_seconds == 20
    assert config.pdf_max_bytes == 50 * 1024 * 1024
    assert config.text_max_bytes == 10 * 1024 * 1024
    assert config.allow_http_urls is False
    assert config.enable_docling is False


def test_review_rerag_config_reads_prefixed_env(monkeypatch) -> None:
    monkeypatch.setenv("PUBTATOR_LINK_DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_CONCURRENCY", "4")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_DOCUMENT_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_SOURCE_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_PDF_MAX_BYTES", "12345")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_TEXT_MAX_BYTES", "6789")
    monkeypatch.setenv("PUBTATOR_LINK_ALLOW_HTTP_URLS", "true")
    monkeypatch.setenv("PUBTATOR_LINK_ENABLE_DOCLING", "true")

    settings = ServerSettings()
    config = ReviewReragConfig.from_settings(settings)

    assert config.database_url == "postgresql://user:pass@localhost/db"
    assert config.prep_concurrency == 4
    assert config.document_timeout_seconds == 30
    assert config.source_timeout_seconds == 10
    assert config.pdf_max_bytes == 12345
    assert config.text_max_bytes == 6789
    assert config.allow_http_urls is True
    assert config.enable_docling is True
