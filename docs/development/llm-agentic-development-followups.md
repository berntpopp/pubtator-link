# LLM-Agentic Development Follow-Ups

Date: 2026-05-03

This report records recommendations from the LLM-agentic development review that
are intentionally not part of the current P0 implementation pass.

## Deferred P0 By Request

### Blocking container security scans

Current state:

- `.github/workflows/container-security.yml` builds an image, runs Trivy, and
  uploads a table report plus CycloneDX SBOM.
- Trivy still uses `exit-code: "0"`, so HIGH/CRITICAL vulnerabilities do not
  fail the workflow.

Recommended next step:

- Change the vulnerability scan to fail on reviewed severities, normally
  `HIGH,CRITICAL`.
- Keep SBOM generation advisory and always uploaded.
- Add a documented exception process for known false positives or accepted
  temporary risk.

Suggested exit criteria:

- Container scan fails on configured severity.
- Exceptions are explicit, reviewed, and time-bounded.
- Release validation cannot publish or promote an image when blocking scan
  findings are present.

## Remaining Repository Controls

### Verify branch protection is active in GitHub

The repo documents branch protection in
`docs/development/branch-protection.md`, but local files cannot prove the GitHub
setting is enabled.

Recommended next step:

- Use repository admin settings or `gh api` to apply the policy in
  `docs/development/branch-protection.json`.
- Periodically verify required check names still match workflow job names.

### Decide release provenance and signing policy

Current release validation builds and checks, but does not publish, sign, or
attach provenance.

Recommended next step:

- Decide whether releases should publish container images, Python artifacts, or
  both.
- If publishing images, add provenance/signing with a maintained mechanism such
  as Sigstore/cosign or GitHub artifact attestations.

## Code Structure Follow-Ups

### Split remaining large modules

Largest remaining implementation files should be split only when touching their
behavior:

- `pubtator_link/repositories/review_rerag.py`
- `pubtator_link/mcp/service_adapters.py`
- `pubtator_link/api/routes/dependencies.py`
- `pubtator_link/models/review_rerag.py`

Recommended approach:

- Extract by stable responsibility, not arbitrary line count.
- Preserve current public REST/MCP behavior with characterization tests first.
- Prefer mapper, query, adapter, and model-family boundaries that match existing
  patterns.

### Generate MCP tool documentation from runtime truth

The MCP surface is large enough that static tables can drift.

Recommended next step:

- Add a docs-generation command that introspects registered MCP tools and writes
  a compact catalog.
- Include tool name, purpose, arguments, output shape, and research-use safety
  notes.
- Test that generated docs are current in CI.

## Hosted Safety Follow-Ups

### Inbound HTTP abuse resistance

Current upstream client rate limiting protects PubTator, not necessarily a
public hosted PubTator-Link instance.

Recommended next step:

- Add explicit request-size limits.
- Add hosted-mode per-IP or per-token rate limiting.
- Narrow CORS methods and headers for production deployments.

### URL and identifier validation hardening

Recommended next step:

- Enforce documented MIME types for curated URL ingestion.
- Validate PubTator-style entity identifiers before passing filters downstream.
- Preserve resolver-attempt diagnostics for rejected inputs.

## MCP Protocol Modernization

Recommended future work:

- Add resource templates for review summaries, passage previews, and tool docs.
- Add parameterized prompts for common research workflows.
- Introduce opaque cursor pagination for drifting review/session inventories.
- Use elicitation only for narrow, human-confirmed ambiguous review mutations.

## Observability Follow-Ups

Recommended future work:

- Add optional OpenTelemetry tracing for route -> MCP -> service -> repository
  paths.
- Add optional error tracking with sanitized request/tool context.
- Promote concurrency stress scripts into marked integration tests.

## References

- Claude Code best practices: <https://code.claude.com/docs/en/best-practices>
- OpenAI Codex agent loop: <https://openai.com/index/unrolling-the-codex-agent-loop/>
- uv GitHub Actions guidance: <https://docs.astral.sh/uv/guides/integration/github/>
- GitHub Actions secure use: <https://docs.github.com/en/actions/reference/security/secure-use>
- MCP security best practices: <https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices>
- MCP server concepts: <https://modelcontextprotocol.io/docs/learn/server-concepts>
