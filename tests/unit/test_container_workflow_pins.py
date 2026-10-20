"""Trusted-builder workflow references must match the released control plane."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRUSTED_BUILDER_SHA = "bab3fb6bc9a9b2a9c87bd3d5aa9883a42bae039b"


def test_all_router_reusable_workflows_use_the_exact_trusted_builder() -> None:
    occurrences: list[str] = []
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "berntpopp/genefoundry-router/.github/workflows/" in line:
                occurrences.append(line.rsplit("@", 1)[-1].split()[0])

    assert occurrences
    assert set(occurrences) == {TRUSTED_BUILDER_SHA}
