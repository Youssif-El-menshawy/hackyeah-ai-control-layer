# Implementation plan

This plan begins only after architecture approval. Each phase keeps the system
runnable and testable; later phases do not change the trust boundaries defined in
the root README.

## Phase 1 — project foundations and contract tests

- Initialize the Python/FastAPI package and Next.js/TypeScript dashboard.
- Pin minimal dependencies and add local development commands.
- Generate/implement Pydantic models from the OpenAPI contract without changing
  the public schema silently.
- Validate policy YAML against the JSON Schema.
- Add pytest contract tests for valid/invalid API payloads and policy documents.

Acceptance: clean installs work, schema validation tests pass, and no endpoint
contains control logic yet.

## Phase 2 — deterministic sanitizer

- Define typed detector and redaction results.
- Implement built-in email, phone, API-key, and secret detectors.
- Canonically serialize tool arguments before scanning.
- Replace findings with stable typed placeholders and never retain matched values.
- Add boundary, Unicode, overlap, false-positive, and property-style tests.

Acceptance: the same input and policy always yield byte-identical sanitized
content and metadata; tests prove raw matches do not enter logs or classifier
calls.

## Phase 3 — policy loading and deterministic checks

- Load and validate YAML; compile it into an immutable policy snapshot.
- Implement atomic reload with SHA-256 policy versioning and last-good fallback.
- Implement model allowlist, per-agent tool permissions, and SQLite-backed rolling
  request/token budget reservations.
- Define stable facts, reason codes, priority ordering, and action precedence.
- Add concurrency tests for budget enforcement and reload snapshot isolation.

Acceptance: decisions are reproducible from policy version plus normalized facts;
invalid reloads never replace the active snapshot.

## Phase 4 — semantic classifier boundary

- Define one async interface accepting sanitized content and returning only the
  normalized labels in the API contract.
- Add a deterministic stub for tests and one external provider adapter selected
  by configuration.
- Enforce timeouts, response bounds, and configured failure behavior.
- Add spy tests proving providers never receive unsanitized content.

Acceptance: swapping providers is configuration-only, and provider responses
cannot directly produce final actions.

## Phase 5 — orchestration, API, and persistence

- Compose validation → sanitization → deterministic checks → semantic signals →
  policy decision → transactional event logging.
- Implement evaluation, event-list, policy metadata/reload, and health endpoints.
- Use SQLite migrations for events, budget windows, and approval records.
- Make repeated `request_id` submissions idempotent.
- Add integration tests across every action and semantic failure path.

Acceptance: all four outcomes are covered end to end; persisted rows contain no
raw secrets; the policy engine alone emits the final action.

## Phase 6 — dashboard

- Show outcome counts, latency, budget consumption, and a paginated event table.
- Show reason codes, redaction counts, semantic signals, and active policy version.
- Add approval queue/status UI and guarded policy reload action.
- Avoid rendering or requesting raw sensitive content.

Acceptance: operators can understand why a decision occurred and can verify which
policy version produced it.

## Phase 7 — hardening and demo readiness

- Add authentication/authorization appropriate to the demo environment.
- Add request-size, timeout, SQLite contention, and malformed-provider tests.
- Document local startup, policy editing, rollback, and demo scenarios.
- Run backend tests, frontend lint/type checks, and a small end-to-end smoke test.

Acceptance: one-command local startup, deterministic demo fixtures, and a written
failure/rollback procedure.

## Initial test matrix

| Area | Essential cases |
| --- | --- |
| Sanitization | each detector, overlaps, multiple matches, Unicode, no-match |
| Isolation | classifier spy sees placeholders only; logs contain hashes/counts |
| Permissions | known/unknown agent, allowed/denied/unspecified tool |
| Models | allowed and unknown model |
| Budgets | below, at, above limit; concurrent requests; window rollover |
| Semantics | low/high injection, low/high exfiltration, timeout, malformed response |
| Decisions | precedence, priority ties, default allow, provider failure action |
| Reload | valid swap, invalid rejection, in-flight snapshot consistency |
| API | prompt/tool-call validation, idempotency, safe error response |

## Approved architecture decisions

1. Unknown agents and unspecified tools are denied by default.
2. `REDACT` continues with sanitized prompts or tool arguments; tool arguments
   are revalidated before execution by the caller.
3. The first external adapter uses OpenAI Responses with Structured Outputs and
   `store: false`. Its model is configuration-only; candidates are benchmarked
   on a labeled corpus before a snapshot is pinned.
4. V1 includes minimal, audited, one-time approval resolution.
5. V1 uses hashed API keys with `evaluate`, `viewer`, `approver`, and `admin`
   scopes.
6. Semantic failures are typed. Tool calls fail closed; prompt fallbacks are
   configured separately for timeout, rate limit, malformed output, and outage.
