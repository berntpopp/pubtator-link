"""Contract Truth v1 gate against the live PubTator MCP registry."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

EXPECTED_HELPER_SHA256 = "e6c12b087c8231f5324c6388abd01afaeffa305a84d0b7c0e3629e17993d3674"


async def test_documentation_matches_live_mcp_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Lint repository documentation against production-relevant tool profiles."""
    helper_path = Path(__file__).with_name("contract_truth.py")
    pin_path = Path(__file__).with_name("contract_truth.sha256")

    vendored_pin = pin_path.read_text(encoding="utf-8").strip()
    assert vendored_pin == EXPECTED_HELPER_SHA256
    assert sha256(helper_path.read_bytes()).hexdigest() == vendored_pin

    from .contract_truth import (
        active_markdown_files,
        historical_markdown_files,
        lint_repository,
    )

    monkeypatch.delenv("PUBTATOR_LINK_MCP_PROFILE", raising=False)
    monkeypatch.chdir(tmp_path)

    from pubtator_link.mcp.facade import create_pubtator_mcp

    full_tools = await create_pubtator_mcp(profile="full").list_tools()
    readonly_tools = await create_pubtator_mcp(profile="readonly").list_tools()

    assert full_tools, "the live full MCP registry must not be empty"
    assert readonly_tools, "the live readonly MCP registry must not be empty"
    assert {tool.name for tool in readonly_tools} <= {tool.name for tool in full_tools}

    catalog: dict[str, dict[str, object]] = {}
    for tools in (full_tools, readonly_tools):
        for tool in tools:
            assert isinstance(tool.parameters, dict)
            advertised = {"inputSchema": tool.parameters}
            previous = catalog.setdefault(tool.name, advertised)
            assert previous == advertised, f"profile schema drift for {tool.name}"

    repo_root = Path(__file__).resolve().parents[2]
    assert active_markdown_files(repo_root), "active Markdown discovery must not be empty"
    assert historical_markdown_files(repo_root), "historical Markdown discovery must not be empty"

    findings = lint_repository(repo_root, catalog)
    rendered = "\n".join(
        f"{finding.path}:{finding.line}: {finding.rule}: {finding.message}" for finding in findings
    )
    assert not findings, rendered
