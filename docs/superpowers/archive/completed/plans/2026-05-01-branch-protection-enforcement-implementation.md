# Branch Protection Enforcement Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a machine-checkable branch protection policy and tests that keep required GitHub check names aligned with workflows.

**Architecture:** Keep `docs/development/branch-protection.md` as the human-readable guide. Add `docs/development/branch-protection.json` as the structured policy and extend development-tooling tests to verify policy shape and workflow check-name consistency.

**Tech Stack:** Python 3.11, pytest, PyYAML, JSON, GitHub Actions, Make.

---

## File Structure

- Create `docs/development/branch-protection.json`: structured branch protection policy.
- Modify `docs/development/branch-protection.md`: reference JSON policy and clarify remote settings must still be enabled in GitHub.
- Modify `tests/unit/test_development_tooling.py`: tests for policy shape and workflow alignment.

## Task 1: Add Structured Branch Protection Policy

**Files:**
- Create: `docs/development/branch-protection.json`
- Modify: `docs/development/branch-protection.md`
- Test: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Write the failing policy existence test**

Add imports and test helpers to `tests/unit/test_development_tooling.py`:

```python
import json
```

Add this test:

```python
def test_branch_protection_policy_file_exists_and_parses() -> None:
    policy_path = Path("docs/development/branch-protection.json")

    assert policy_path.exists()
    policy = json.loads(policy_path.read_text())

    assert policy["branch"] == "main"
    assert policy["required_review_count"] == 1
    assert policy["dismiss_stale_reviews"] is True
    assert policy["require_up_to_date_branch"] is True
    assert policy["postgres_integration_required"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/unit/test_development_tooling.py::test_branch_protection_policy_file_exists_and_parses -q
```

Expected: fail because `docs/development/branch-protection.json` does not exist.

- [ ] **Step 3: Add the JSON policy**

Create `docs/development/branch-protection.json`:

```json
{
  "branch": "main",
  "require_pull_request": true,
  "required_review_count": 1,
  "dismiss_stale_reviews": true,
  "require_status_checks": true,
  "require_up_to_date_branch": true,
  "postgres_integration_required": false,
  "required_status_checks": [
    "CI / Format, lint, typecheck, tests, and coverage",
    "Docker / Docker build and Compose validation",
    "Security / CodeQL",
    "Security / Dependency review"
  ],
  "optional_settings": [
    "Require linear history",
    "Require conversation resolution before merging",
    "Restrict pushes to repository maintainers or release automation"
  ]
}
```

- [ ] **Step 4: Update the Markdown guide**

Add this paragraph after the title in `docs/development/branch-protection.md`:

```markdown
The machine-checkable policy is recorded in
`docs/development/branch-protection.json`. Tests verify that the policy's
required check names stay aligned with workflow job names. The JSON file does
not prove GitHub settings are enabled; repository administrators still need to
apply the settings in GitHub.
```

- [ ] **Step 5: Run the focused test**

```bash
uv run pytest tests/unit/test_development_tooling.py::test_branch_protection_policy_file_exists_and_parses -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add docs/development/branch-protection.json docs/development/branch-protection.md tests/unit/test_development_tooling.py
git commit -m "docs: add structured branch protection policy"
```

## Task 2: Verify Required Checks Match Workflow Names

**Files:**
- Modify: `tests/unit/test_development_tooling.py`
- Test: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Write the workflow alignment test**

Add this helper near `_workflow`:

```python
def _branch_protection_policy() -> dict[str, Any]:
    return json.loads(Path("docs/development/branch-protection.json").read_text())
```

Add this test:

```python
def test_branch_protection_required_checks_match_workflow_job_names() -> None:
    policy = _branch_protection_policy()
    workflows = {
        "CI": _workflow(".github/workflows/ci.yml"),
        "Docker": _workflow(".github/workflows/docker.yml"),
        "Security": _workflow(".github/workflows/security.yml"),
    }
    workflow_checks = {
        f"{workflow_name} / {job['name']}"
        for workflow_name, workflow in workflows.items()
        for job in workflow["jobs"].values()
    }

    assert set(policy["required_status_checks"]) == {
        "CI / Format, lint, typecheck, tests, and coverage",
        "Docker / Docker build and Compose validation",
        "Security / CodeQL",
        "Security / Dependency review",
    }
    assert set(policy["required_status_checks"]).issubset(workflow_checks)
```

- [ ] **Step 2: Run the focused test**

```bash
uv run pytest tests/unit/test_development_tooling.py::test_branch_protection_required_checks_match_workflow_job_names -q
```

Expected: pass.

- [ ] **Step 3: Run all development tooling tests**

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_development_tooling.py
git commit -m "test: verify branch protection check names"
```

## Task 3: Final Verification

**Files:**
- Check: `docs/development/branch-protection.json`
- Check: `docs/development/branch-protection.md`
- Check: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Run focused tests**

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run full gate**

```bash
make ci-local
```

Expected: exits 0.

- [ ] **Step 3: Check for final cleanup changes**

Run:

```bash
git status --short
```

If the listed branch-protection files changed during verification, commit them:

```bash
git add docs/development/branch-protection.json docs/development/branch-protection.md tests/unit/test_development_tooling.py
git commit -m "docs: finalize branch protection enforcement policy"
```

If `git status --short` is empty, do not create an empty commit for this task.

## Plan Self-Review Checklist

- Spec coverage: structured policy, docs clarification, workflow-name tests, and operator boundary are covered.
- Placeholder scan: no placeholders.
- Type consistency: JSON helpers return `dict[str, Any]`; test uses existing `_workflow` helper.
