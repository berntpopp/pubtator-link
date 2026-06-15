from pathlib import Path


def test_live_surface_smoke_script_exists() -> None:
    script = Path("scripts/smoke_mcp_tool_surface.py")
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "convert_article_ids" in text
    assert "find_entity_relations" in text
    assert "max_response_chars" in text
