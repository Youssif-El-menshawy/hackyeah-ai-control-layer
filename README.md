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
is held only in page state. The example policy uses the offline `stub` provider;
to exercise the external adapter, set `semantic.provider: openai` and set a
configuration-selected `semantic.model`. The application contains no default
OpenAI model identifier.

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
