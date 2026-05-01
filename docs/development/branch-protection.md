# Branch Protection

The machine-checkable policy is recorded in
`docs/development/branch-protection.json`. Tests verify that the policy's
required check names stay aligned with workflow job names. The JSON file does
not prove GitHub settings are enabled; repository administrators still need to
apply the settings in GitHub.

Recommended branch protection for `main`:

- Require pull request before merging.
- Require at least one approval before merging.
- Dismiss stale pull request approvals when new commits are pushed.
- Require status checks to pass before merging.
- Require branches to be up to date before merging.

Required status checks:

- `CI / Format, lint, typecheck, tests, and coverage`
- `Docker / Docker build and Compose validation`
- `Security / CodeQL`
- `Security / Dependency review`

The CI check runs `make ci-local` and `make test-cov`, including the coverage
baseline enforced in `pyproject.toml`.

Docker validation runs the Compose configuration checks with
`make docker-prod-config` and `make docker-npm-config`, then builds the image with
`docker build -f docker/Dockerfile -t pubtator-link:ci .`.

Security CodeQL runs Python CodeQL analysis. Security Dependency Review runs on
pull requests to flag dependency changes before merge.

Optional settings:

- Require linear history.
- Require conversation resolution before merging.
- Restrict pushes to repository maintainers or release automation.

PostgreSQL integration tests remain optional for branch protection unless a
reliable database URL secret or service container is available in CI.
