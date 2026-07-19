# Branch Protection Enforcement Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-01

## Goal

Turn the documented `main` branch protection guidance into a concrete,
auditable repo workflow without changing application runtime behavior.

## Problem

The repository already documents recommended branch protection in
`docs/development/branch-protection.md`, and GitHub Actions now provide CI,
Docker validation, CodeQL, and dependency review checks. The remaining gap is
that repo-local files do not make it easy to verify or apply those settings
consistently.

GitHub branch protection itself is a repository setting, not a code change. A
local implementation plan should therefore prepare exact enforcement artifacts
and checks, while leaving the final GitHub settings mutation as an explicit
operator action unless the user later requests GitHub API execution.

## Non-Goals

- Do not mutate GitHub repository settings during implementation by default.
- Do not add new CI jobs unless needed to clarify required check names.
- Do not require PostgreSQL integration tests for branch protection.
- Do not change application code.
- Do not change workflow behavior beyond documentation or validation
  refinements.

## Proposed Design

Keep `docs/development/branch-protection.md` as the source of truth for the
human-readable policy. Add a small machine-checkable branch protection
definition under `docs/development/`, plus tests that verify the documented
check names match existing workflow job names.

Suggested artifact:

- `docs/development/branch-protection.json`
  - records required review settings.
  - records required status check names.
  - records optional settings separately from required settings.

Suggested tests:

- extend `tests/unit/test_development_tooling.py` to assert:
  - the JSON policy exists and parses.
  - required check names include the CI, Docker, CodeQL, and dependency review
    job names.
  - each required check name appears in a workflow file.
  - PostgreSQL integration tests are documented as optional.

This creates a repo-local evidence trail for branch protection without
pretending local tests can prove GitHub settings are enabled.

## Required Policy

The required policy should match the current document:

- Require pull request before merging.
- Require at least one approval.
- Dismiss stale approvals when new commits are pushed.
- Require status checks to pass before merging.
- Require branches to be up to date before merging.

Required checks:

- `CI / Format, lint, typecheck, tests, and coverage`
- `Docker / Docker build and Compose validation`
- `Security / CodeQL`
- `Security / Dependency review`

Optional settings:

- Require linear history.
- Require conversation resolution.
- Restrict pushes to maintainers or automation.

## Data Flow

1. Workflows define job names.
2. `docs/development/branch-protection.json` records required check names.
3. Development-tooling tests compare the policy with workflow contents.
4. Operators use the JSON and Markdown docs to configure GitHub settings.

## Error Handling

If workflow names drift, tests should fail with an assertion showing the missing
required check. If the JSON policy is malformed, tests should fail during JSON
load. The implementation should not silently skip unknown workflow files.

## Testing

Focused tests:

```bash
uv run pytest tests/unit/test_development_tooling.py -q
```

Completion gate:

```bash
make ci-local
```

## Rollout

1. Add JSON branch protection policy.
2. Update Markdown docs to reference the JSON policy.
3. Add tooling tests that lock policy and workflow check names together.
4. Run focused tests and `make ci-local`.
5. After merge, an operator enables the matching settings in GitHub.

## Risks And Mitigations

Risk: local tests create false confidence that GitHub branch protection is
enabled.

Mitigation: docs and test names must say the repo contains an enforceable policy
definition, not proof of remote settings.

Risk: required check names differ from GitHub display names.

Mitigation: derive expected names from workflow `name` plus job `name` values
and keep them explicit in tests.
