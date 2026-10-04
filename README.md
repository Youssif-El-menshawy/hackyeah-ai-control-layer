# HackYeah AI Control Layer

Architecture-first scaffold for a control plane that evaluates agent prompts and
tool calls before they reach a model or external tool. This repository currently
contains contracts and design documents only; application code intentionally
waits for architecture approval.

## Goals

- Apply deterministic sanitization before any semantic provider sees content.
- Combine deterministic checks and semantic risk signals in a deterministic,
  locally owned policy decision.
- Return exactly one enforcement action: `ALLOW`, `REDACT`, `BLOCK`, or
  `REQUIRE_APPROVAL`.
- Keep policies, model allowlists, permissions, thresholds, and budgets in YAML.
- Persist decisions and operational telemetry in SQLite without storing raw
  sensitive input by default.

## Proposed architecture

```text
Next.js dashboard
        |
        v
FastAPI API -> request validation
        |
        v
deterministic sanitizer -----> sanitized content only
        |                              |
        v                              v
deterministic checks           semantic classifier adapter
        |                              |
        +---------- signals -----------+
                       |
                       v
             deterministic policy engine
                       |
         ALLOW / REDACT / BLOCK / REQUIRE_APPROVAL
                       |
                       v
             SQLite event + telemetry log
```

The semantic adapter can label sanitized text (for example, prompt-injection or
exfiltration risk) and return bounded scores. It cannot choose the final action.
The policy engine maps facts and signals to an action using versioned YAML rules,
fixed precedence, and explicit thresholds.

## Request lifecycle

1. FastAPI validates a prompt or tool-call envelope.
2. The sanitizer detects and replaces email addresses, phone numbers, API keys,
   and secrets using stable placeholders.
3. Deterministic checks evaluate agent/tool permissions, model allowlists, and
   request/token budgets.
4. A semantic adapter receives **only sanitized content** and returns normalized
   risk signals. Provider-specific output never enters the policy engine.
5. The policy engine evaluates the immutable policy snapshot used for the
   request. Rule priority and action precedence make the result reproducible.
6. The API returns `ALLOW`, `REDACT`, `BLOCK`, or `REQUIRE_APPROVAL` plus safe
   reason codes and, where applicable, sanitized content.
7. SQLite records policy version, checks, semantic signals, outcome, latency,
   token accounting, and content hashes. Raw input is excluded by default.

## Trust boundaries and invariants

- Raw input may exist only in the API/sanitization boundary and is not sent to a
  semantic provider or persisted by default.
- Adapters implement one internal semantic-classifier protocol and translate
  provider responses into a closed set of labels and scores.
- The policy engine is the sole owner of final decisions. A semantic provider
  supplies evidence, never an enforcement action.
- Semantic timeout, rate-limit, malformed-output, and outage failures are mapped
  by policy. Tool calls always fail closed; prompt fallbacks are configurable.
- Each evaluation uses one atomic, validated policy snapshot. Reload failures
  leave the last valid snapshot active.
- Decision precedence is `BLOCK > REQUIRE_APPROVAL > REDACT > ALLOW`, unless an
  explicit rule with a higher numeric priority applies. Ties use this precedence.
- Budget reservation and event persistence occur in one SQLite transaction to
  avoid concurrent overspend.
- Logs contain hashes, counts, reason codes, and redaction metadata—not recovered
  secret values.

## Modules

| Path | Responsibility |
| --- | --- |
| `backend/src/control_layer/api` | HTTP routing, auth boundary, request/response mapping |
| `backend/src/control_layer/core` | orchestration, sanitizer contracts, decision types |
| `backend/src/control_layer/policy` | YAML loading, validation, snapshots, deterministic evaluation |
| `backend/src/control_layer/semantic` | provider-neutral interface and provider adapters |
| `backend/src/control_layer/storage` | SQLite repositories, migrations, budget transactions |
| `backend/tests` | unit and contract/integration tests |
| `dashboard/src` | Next.js dashboard for decisions, events, approvals, and policy status |
| `contracts/openapi.yaml` | versioned HTTP API contract |
| `policies/policy.schema.json` | machine-readable YAML/JSON policy schema |
| `policies/example.policy.yaml` | non-production example configuration |
| `docs/IMPLEMENTATION_PLAN.md` | staged delivery and acceptance gates |

## Configuration and reload model

The process is started with a path to a YAML policy. The loader validates it
against `policies/policy.schema.json`, compiles regexes and rules, computes a
SHA-256 version, then atomically swaps the active immutable snapshot. Reload can
be triggered by a guarded API call or a filesystem watcher; both use the same
loader. Invalid updates are rejected and logged without replacing the active
policy. No policy setting is hard-coded in application code.

## Intentional V1 exclusions

No message broker, distributed database, Kubernetes setup, vector store, custom
model training, or multi-service deployment is proposed. FastAPI, Next.js, one
policy file, and SQLite are sufficient for the prototype.

## Current status

The V1 prototype is implemented with a tested FastAPI backend and a minimal
Next.js operations dashboard.

## Local development

```bash
cp .env.example .env
cd backend && uv sync --extra dev
set -a; source ../.env; set +a
uv run python -m control_layer
```

For development with automatic reload, run from `backend` with the same environment:

```bash
uv run uvicorn control_layer.api.app:create_app --factory --reload --port 8000
```

The ASGI entrypoint is the `create_app` factory; there is no module-level `app`.
Docs are at `http://127.0.0.1:8000/docs` and health at
`http://127.0.0.1:8000/api/v1/health`. The default `stub` provider requires no
OpenAI credentials. With `provider: openai`, missing or blank `OPENAI_API_KEY`
produces the configured `outage` fallback during evaluation.

In a second terminal:

```bash
cd dashboard
npm install
npm run dev
```

Open `http://localhost:3000` and enter the API key configured in `.env`. The key
is held only in page memory across Overview and Benchmark navigation; it is
cleared by Disconnect or a full reload. Overview shows a bounded snapshot of
the latest 100 audit events, with 12 rows per page and filters for decision,
agent, request type, and request ID/reason text. Its summary and activity counts
cover that 100-event sample, not all historical events. Event details expose
recorded safe metadata, redaction summaries, scores, request IDs and fingerprints.
The audit log does not retain sanitized content, exact failed deterministic
facts, or all matched rule IDs, so the detail drawer marks those unavailable.

Live data refreshes about every five seconds while the page is visible. Hidden
tabs pause; returning to the tab refreshes immediately. Manual Refresh and
Approve/Deny refresh immediately, and a temporary backend outage leaves the
last successful view visible. Policy definitions and benchmark reports are
loaded on navigation or explicit refresh, not polled every five seconds.

The compact Self-tests card reads the latest real backend pytest summary. Run
`cd backend && uv run pytest` to write `backend/latest_test_results.json`
atomically; the dashboard never starts tests. `GET /api/v1/tests/latest`
requires a `viewer` or `admin` key and returns only counts, duration, completion
time, and run status. It returns `null` until a run exists. Set
`CONTROL_LAYER_TEST_RESULTS_PATH` to the same path for pytest and the API if
using a custom location. The top-nav theme switch follows the system preference
on first visit and saves an explicit light/dark choice locally in the browser.

The example policy currently configures the `openai` semantic provider and a
model in YAML. Both can be changed without code edits; the application contains
no default OpenAI model identifier. Without provider credentials, the configured
failure policy applies to evaluations.

To benchmark an account-available candidate before pinning it, use a separate
policy file with `semantic.provider: openai` and its configured model, then run:

```bash
cd backend
uv run python scripts/benchmark_semantic.py \
  --policy ../policies/candidate.policy.yaml \
  --schema ../policies/policy.schema.json \
  --corpus tests/fixtures/security_corpus.jsonl
```

The included corpus is a small smoke fixture, not a production evaluation set;
expand it with representative multilingual, obfuscated, benign, and adversarial
examples before selecting and pinning a provider snapshot.

### Benchmark results dashboard

Open `/benchmark` in the dashboard and connect with a `viewer` or `admin` API key.
The page is read-only: it never starts a benchmark. Until a report exists it shows
**No benchmark results yet** after connecting. No demo scores are seeded.
The included eight-case corpus and its results are a **smoke-test benchmark, not
production-grade validation**. Scores do not validate the overall security layer.

Run the existing harness manually, in a shell with `OPENAI_API_KEY` exported:

```bash
cd backend
uv run python scripts/benchmark_semantic.py \
  --policy ../policies/example.policy.yaml \
  --schema ../policies/policy.schema.json \
  --corpus tests/fixtures/security_corpus.jsonl \
  --output benchmark-results/latest.json
```

This calls the configured external model and may incur API charges. No model is
hard-coded. The CLI also defaults to the same `CONTROL_LAYER_POLICY_PATH` and
`CONTROL_LAYER_POLICY_SCHEMA_PATH` configuration as the backend. It freezes one
validated YAML snapshot at run start and uses the **exact per-label thresholds
and comparison operators** in that snapshot (currently injection `>= 0.65`,
exfiltration `>= 0.8`). It does not use the old shared `0.65` default.
If a policy was edited on disk but not reloaded in a running server, reload it
first when you want the benchmark to represent the live policy. The report stores
its policy hash; the dashboard warns when that hash differs from the live server.

Optional `--prompt-injection-threshold` and `--data-exfiltration-threshold` flags
explicitly override a label with a `>=` cutoff. The retained `--threshold` flag
overrides both; per-label flags take precedence. Overrides are marked in JSON and
the UI. Missing, disabled, compound, unsupported, or conflicting policy cutoffs
require an explicit override rather than an invented threshold. No policy is edited.

The CLI emits one complete JSON document to stdout and atomically publishes the
same report to `--output`. Exit codes: `0` = all cases scored; `2` = completed run
with provider failures (report still saved); `1` = invalid configuration/input or
unreadable files (no report published). The latest report replaces the previous
one; use a separate `--output` path to retain other runs. Interrupted runs leave
the previous complete report in place. Reports under `backend/benchmark-results/`
are git-ignored, and test reports stay in temporary directories.

`CONTROL_LAYER_BENCHMARK_PATH` configures the CLI's default output and the API's
read path. Both default to `backend/benchmark-results/latest.json` relative to the
repository root; explicitly configured relative paths resolve from each process's
working directory. `GET /api/v1/benchmarks/latest` requires `viewer` (or `admin`),
returns JSON `null` if absent, and returns a generic 503 for an invalid report.
It does not execute classifiers or modify events, budgets, approvals, or policy.

Reports contain UTC timestamps, configured and provider-reported model IDs, policy
and corpus hashes, thresholds, coverage, latency, runtime, per-label metrics and
TP/TN/FP/FN counts. A snapshot is displayed only when a unique dated model ID was
actually reported; aliases remain explicitly unverified. Per-case rows use
sequential opaque IDs corresponding to nonblank corpus rows. Neither prompt text
(raw or sanitized), original corpus IDs, provider response text, nor exception
messages are exported. The existing sanitizer still runs before classification.

Coverage is successful classifications divided by all corpus cases. Provider
failures have null predictions/scores and are excluded from classification metrics;
they are not safe negatives. Accuracy is `(TP+TN)/evaluated`, precision `TP/(TP+FP)`,
recall `TP/(TP+FN)`, F1 `2TP/(2TP+FP+FN)`, false-positive rate `FP/(FP+TN)` and
false-negative rate `FN/(FN+TP)`. Undefined denominators yield null / **N/A**.
Average latency covers every classification attempt, including failures; total
runtime covers sanitization and classification of the corpus, excluding file I/O
and initial client setup.

Cost is **Unavailable** by default, never a fabricated zero. Supply `--pricing`
with a JSON object containing `model` (exact configured ID),
`input_usd_per_million`, `output_usd_per_million`, and optionally
`cached_input_usd_per_million`, using rates you have verified for your account.
The report records these explicit rates and estimates USD from provider-reported
usage. If any attempt lacks usage, cached tokens lack a price, or cache-write
tokens are reported, the total remains unavailable. This is an estimate, not an
invoice; account discounts and other billing adjustments are not inferred.

Response metadata fields follow the [OpenAI Responses reference](https://developers.openai.com/api/reference/python/resources/responses/methods/retrieve).
Metadata collection is benchmark-only through the adapter's existing injectable
client; the semantic interface, normal evaluation flow, and decision engine are unchanged.
