from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

WorkflowTask = Literal[
    "clinical_genetics_review",
    "literature_review",
    "citation_audit",
    "entity_discovery",
]


class WorkflowStep(BaseModel):
    order: int
    tool_name: str
    purpose: str
    required: bool = True
    key_args: dict[str, Any] = Field(default_factory=dict)


class WorkflowFallback(BaseModel):
    condition: str
    tool_name: str
    action: str


class WorkflowHelpResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    task: WorkflowTask
    steps: list[WorkflowStep]
    fallbacks: list[WorkflowFallback]
    tool_sequence: list[str]
    meta: dict[str, Any] = Field(default_factory=dict, alias="_meta")
