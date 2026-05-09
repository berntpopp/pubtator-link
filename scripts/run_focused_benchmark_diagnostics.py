"""Run configured LLM diagnostics for a focused benchmark report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from scripts.run_single_case_provider_benchmark import _run_provider


def _render_prompt(template_path: Path, values: dict[str, str]) -> str:
    rendered = template_path.read_text()
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", value)
    return rendered


def _provider_text(raw: dict[str, Any]) -> str:
    stdout = str(raw.get("stdout", ""))
    if stdout.strip().startswith("{"):
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            text = stdout
        else:
            text = str(
                parsed.get("result") or parsed.get("response") or parsed.get("content") or stdout
            )
    else:
        text = stdout
    noise_prefixes = (
        "No matching skill found.",
        "Proceeding with direct analysis",
    )
    lines = [
        line
        for line in text.splitlines()
        if not any(line.startswith(prefix) for prefix in noise_prefixes)
    ]
    return "\n".join(lines).strip()


def _run_section(section: dict[str, Any], report_markdown: str, artifact_root: str) -> None:
    prompt = _render_prompt(
        Path(section["prompt"]),
        {
            "report_markdown": report_markdown,
            "artifact_root": artifact_root,
        },
    )
    raw = _run_provider(section["provider"], section["model"], prompt, int(section["timeout_s"]))
    output = Path(section["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_provider_text(raw).strip() + "\n")
    raw_output = output.with_suffix(output.suffix + ".raw.json")
    raw_output.write_text(json.dumps(raw, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="benchmarks/configs/focused_default.yaml")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text())
    report_markdown = Path(config["report_path"]).read_text()
    _run_section(config["judge"], report_markdown, str(config["artifact_root"]))
    _run_section(config["self_assessment"], report_markdown, str(config["artifact_root"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
