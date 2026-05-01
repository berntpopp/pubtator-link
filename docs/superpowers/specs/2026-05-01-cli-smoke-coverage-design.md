# CLI Smoke Coverage Design

Date: 2026-05-01

## Goal

Add focused CLI smoke tests that improve coverage margin without making network
calls or changing CLI behavior.

## Problem

`pubtator_link/cli.py` is intentionally included in coverage, but it has little
direct test coverage. Current total coverage is above the 80% gate, but the
margin is still narrow. The CLI is a shipped console entry point, so basic
parser and dispatch behavior should be locked by tests.

## Non-Goals

- Do not replace `argparse` with another CLI framework.
- Do not perform live PubTator or network calls.
- Do not test Rich rendering in detail.
- Do not change command names, arguments, defaults, or exit semantics unless a
  test exposes an existing bug.
- Do not add slow subprocess-based tests unless direct function tests cannot
  cover the behavior.

## Proposed Design

Keep the CLI implementation unchanged. Add direct unit tests around
`pubtator_link.cli.main()` and selected async command helpers using monkeypatches
and mocks.

Create `tests/unit/test_cli.py` with tests for:

- top-level help path when no command is provided.
- `serve` help path when no serve mode is provided.
- dispatch to `serve_http` with default and supplied host/port values.
- dispatch to `serve_unified`.
- dispatch to `serve_mcp_only`.
- dispatch to `search_entities`, `search_publications`, and
  `export_publications` without calling external services.
- `test` command exit code mapping for successful and failed connection checks.

The tests should patch `sys.argv`, patch `asyncio.run` where command dispatch is
the behavior under test, and patch command functions with simple sentinels.
Tests for async helpers can be added only where they can mock
`PubTator3Client` cleanly and without network access.

## Public Contract

The following commands and arguments must remain stable:

- `pubtator-link test`
- `pubtator-link serve http --host --port --reload`
- `pubtator-link serve unified --host --port --reload`
- `pubtator-link serve mcp`
- `pubtator-link entities QUERY --concept --limit`
- `pubtator-link search QUERY --page`
- `pubtator-link export PMIDS --format --full`

## Testing Strategy

Use behavior tests around dispatch rather than snapshots of full Rich output.
Assertions should focus on:

- command function called with expected arguments.
- `SystemExit` code for `test`.
- help paths return without dispatching commands.
- invalid parser choices can rely on argparse behavior and do not need broad
  coverage.

Focused command:

```bash
uv run pytest tests/unit/test_cli.py -q
```

Coverage gate:

```bash
make test-cov
```

Completion gate:

```bash
make ci-local
```

## Rollout

1. Add parser/dispatch tests for no-command and serve-no-mode help paths.
2. Add command dispatch tests with patched `asyncio.run`.
3. Add exit-code tests for the `test` command.
4. Run focused tests, `make test-cov`, and `make ci-local`.

## Risks And Mitigations

Risk: tests become brittle by asserting Rich-formatted output.

Mitigation: assert dispatch behavior and exit codes, not full terminal strings.

Risk: tests accidentally call the real PubTator API.

Mitigation: patch command helpers before invoking `main()` and avoid invoking
network-backed helper internals unless their clients are mocked.
