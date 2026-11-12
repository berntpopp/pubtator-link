"""Advertised integer bounds must not be looser than the request model (#248).

A value the schema accepts but the model rejects raises a pydantic ValidationError
inside the tool body: the caller sent a valid request and got an error.
"""

from typing import Any

import pytest
from pydantic import BaseModel

from pubtator_link.mcp.facade import create_pubtator_mcp
from pubtator_link.models.publication_passages import PublicationPassageRequest
from pubtator_link.models.review_rerag import RetrieveReviewContextRequest

# Tools whose impl passes these arguments straight into the request model.
PASS_THROUGH: dict[str, type[BaseModel]] = {
    "get_publication_passages": PublicationPassageRequest,
    "get_review_context": RetrieveReviewContextRequest,
}


def _bounds(schema: dict[str, Any]) -> tuple[float, float]:
    return schema.get("minimum", float("-inf")), schema.get("maximum", float("inf"))


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(PASS_THROUGH))
async def test_tool_integer_bounds_within_model_bounds(tool_name: str) -> None:
    facade: Any = create_pubtator_mcp(profile="full")
    tool = next(t for t in await facade.list_tools() if t.name == tool_name)
    model_props = PASS_THROUGH[tool_name].model_json_schema()["properties"]
    checked = 0
    for name, prop in tool.parameters["properties"].items():
        if prop.get("type") != "integer" or name not in model_props:
            continue
        tool_min, tool_max = _bounds(prop)
        model_min, model_max = _bounds(model_props[name])
        assert tool_min >= model_min and tool_max <= model_max, (
            f"{tool_name}.{name}: schema [{tool_min}, {tool_max}] "
            f"looser than model [{model_min}, {model_max}]"
        )
        checked += 1
    assert checked, f"no integer bounds compared for {tool_name}"
