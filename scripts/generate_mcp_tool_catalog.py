from __future__ import annotations

from pathlib import Path

from pubtator_link.mcp.catalog_docs import render_tool_catalog_markdown


def main() -> None:
    Path("docs/mcp-tool-catalog.md").write_text(render_tool_catalog_markdown())


if __name__ == "__main__":
    main()
