from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from pubtator_link.benchmarks.models import BenchmarkCase, SuiteConfig


def load_suite(path: Path) -> SuiteConfig:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"suite YAML must be a mapping: {path}")
    return SuiteConfig.model_validate(data)


def load_cases(path: Path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw: Any = json.loads(line)
            cases.append(BenchmarkCase.model_validate(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"failed to parse {path}:{line_number}: {exc}") from exc
    return cases


def sample_cases(cases: list[BenchmarkCase], seed: int, count: int) -> list[BenchmarkCase]:
    del seed
    if count >= len(cases):
        return list(cases)
    return list(cases[:count])
