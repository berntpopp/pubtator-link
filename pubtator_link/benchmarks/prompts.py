from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pubtator_link.benchmarks.models import PromptContext


class PromptTemplate(BaseModel):
    path: Path
    text: str
    template_hash: str


class RenderedPrompt(BaseModel):
    text: str
    template_hash: str
    resolved_hash: str


def load_prompt_template(path: Path) -> PromptTemplate:
    raw = path.read_bytes()
    return PromptTemplate(
        path=path,
        text=raw.decode("utf-8"),
        template_hash=hashlib.sha256(raw).hexdigest(),
    )


def render_prompt(
    template_path: Path,
    prompt_contexts: list[PromptContext],
    run_metadata: dict[str, Any] | None = None,
) -> RenderedPrompt:
    template = load_prompt_template(template_path)
    cases_json = json.dumps(
        [context.model_dump(mode="json") for context in prompt_contexts],
        sort_keys=True,
        separators=(",", ":"),
    )
    run_metadata_json = json.dumps(run_metadata or {}, sort_keys=True, separators=(",", ":"))
    text = template.text.replace("{{ cases_json }}", cases_json)
    text = text.replace("{{ run_metadata_json }}", run_metadata_json)
    return RenderedPrompt(
        text=text,
        template_hash=template.template_hash,
        resolved_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
