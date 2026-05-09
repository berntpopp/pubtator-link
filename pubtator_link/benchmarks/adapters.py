from __future__ import annotations

import json
import shutil
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from pubtator_link.benchmarks.models import BenchmarkCase, BenchmarkMode, PredictionRecord
from pubtator_link.benchmarks.prompts import RenderedPrompt


class AdapterNotAvailable(RuntimeError):  # noqa: N818
    """Raised when a live CLI adapter is not enabled in the local environment."""


class AnswerStack(BaseModel):
    adapter: str
    model: str


class AdapterRequest(BaseModel):
    prompt: RenderedPrompt
    cases: list[BenchmarkCase]
    mode: BenchmarkMode
    model: str = "deterministic"
    output_dir: Path | None = None
    timeout_s: int | None = None


class AdapterResult(BaseModel):
    exit_status: int
    predictions: list[PredictionRecord] = Field(default_factory=list)
    raw_output: dict[str, object] = Field(default_factory=dict)
    events: list[dict[str, object]] = Field(default_factory=list)
    cost_usd: float | None = None
    resolved_model: str | None = None


class CliAdapter(Protocol):
    name: str

    def version(self) -> str | None: ...

    def run(self, request: AdapterRequest) -> AdapterResult: ...


def parse_answer_stack(value: str) -> AnswerStack:
    if ":" not in value:
        raise ValueError("answer stack must be adapter:model")
    adapter, model = value.split(":", 1)
    return AnswerStack(adapter=adapter, model=model)


class DryRunAdapter:
    name = "dry_run"

    def version(self) -> str | None:
        return "deterministic"

    def run(self, request: AdapterRequest) -> AdapterResult:
        predictions: list[PredictionRecord] = []
        for case in request.cases:
            if case.dataset == "pubmedqa":
                predictions.append(
                    PredictionRecord(
                        case_id=case.case_id,
                        predicted_label=case.gold_label or "maybe",
                        cited_pmids=case.gold_evidence_pmids
                        if request.mode != BenchmarkMode.NO_TOOLS
                        else [],
                    )
                )
            else:
                predictions.append(
                    PredictionRecord(
                        case_id=case.case_id,
                        predicted_answer=str(case.gold_answer.get("reference_ideal_answer", "")),
                        cited_pmids=case.gold_evidence_pmids
                        if request.mode != BenchmarkMode.NO_TOOLS
                        else [],
                    )
                )
        return AdapterResult(
            exit_status=0,
            predictions=predictions,
            raw_output={"adapter": self.name, "dry_run": True},
            resolved_model=request.model,
        )


@dataclass
class ClaudeCodeAdapter:
    name: str = "claude_code"

    def version(self) -> str | None:
        return shutil.which("claude")

    def run(self, request: AdapterRequest) -> AdapterResult:
        if shutil.which("claude") is None:
            raise AdapterNotAvailable("claude CLI is not installed")
        output_dir = request.output_dir or Path(".")
        debug_file = output_dir / "answer_debug.log"
        command = [
            "claude",
            "--print",
            "--disable-slash-commands",
            "--output-format",
            "json",
            "--debug-file",
            str(debug_file),
            "--permission-mode",
            "bypassPermissions",
        ]
        if request.mode == BenchmarkMode.NO_TOOLS:
            command.extend(["--tools", ""])
        else:
            command.extend(
                [
                    "--allowedTools",
                    "pubtator.search_publications,pubtator.get_publication_passages",
                ]
            )
        completed = subprocess.run(  # noqa: S603
            command,
            input=request.prompt.text,
            text=True,
            capture_output=True,
            timeout=request.timeout_s,
            check=False,
        )
        raw: dict[str, object] = {"stdout": completed.stdout, "stderr": completed.stderr}
        with suppress(json.JSONDecodeError):
            raw = json.loads(completed.stdout)
        return AdapterResult(exit_status=completed.returncode, raw_output=raw)


class CodexCliAdapter:
    name = "codex_cli"

    def version(self) -> str | None:
        return shutil.which("codex")

    def run(self, request: AdapterRequest) -> AdapterResult:
        raise AdapterNotAvailable("codex_cli live adapter is a manual v1 follow-up")


class GeminiCliAdapter:
    name = "gemini_cli"

    def version(self) -> str | None:
        return shutil.which("gemini")

    def run(self, request: AdapterRequest) -> AdapterResult:
        raise AdapterNotAvailable("gemini_cli live adapter is a manual v1 follow-up")


def adapter_registry() -> dict[str, CliAdapter]:
    return {
        "dry_run": DryRunAdapter(),
        "claude_code": ClaudeCodeAdapter(),
        "codex_cli": CodexCliAdapter(),
        "gemini_cli": GeminiCliAdapter(),
    }
