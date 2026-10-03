"""Trusted-builder workflow references must match the released control plane."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRUSTED_BUILDER_SHA = "0122f6e6d8f6a9057b80134d7cacbf61c5bd2e84"


def test_all_router_reusable_workflows_use_the_exact_trusted_builder() -> None:
    occurrences: list[str] = []
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "berntpopp/genefoundry-router/.github/workflows/" in line:
                occurrences.append(line.rsplit("@", 1)[-1].split()[0])

    assert occurrences
    assert set(occurrences) == {TRUSTED_BUILDER_SHA}
