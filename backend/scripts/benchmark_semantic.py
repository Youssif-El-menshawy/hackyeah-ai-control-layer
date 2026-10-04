from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from control_layer.benchmark import (
    LABELS, BenchmarkCase, BenchmarkReport, CaseLabel, Pricing, TokenUsage,
    divide, estimate_cost, metrics_for, policy_thresholds, write_report,
)
from control_layer.core.detectors import DeterministicSanitizer
from control_layer.policy.loader import PolicyStore
from control_layer.semantic.openai_adapter import OpenAIResponsesClassifier

ROOT = Path(__file__).resolve().parents[2]


class ResponseMetadata:
    """Benchmark-only SDK wrapper: retain allowlisted metadata, never response text."""

    def __init__(self, responses):
        self.responses = responses
        self.reset()

    def reset(self):
        self.model = None
        self.usage = None

    async def create(self, **kwargs):
        response = await self.responses.create(**kwargs)
        model = getattr(response, "model", None)
        if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model):
            self.model = model
        usage = getattr(response, "usage", None)
        if usage is not None:
            try:
                self.usage = TokenUsage(
                    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    cached_input_tokens=usage.input_tokens_details.cached_tokens,
                    cache_write_tokens=getattr(usage.input_tokens_details, "cache_write_tokens", 0),
                )
            except (AttributeError, TypeError, ValueError):
                pass
        return response


def load_corpus(path: Path):
    raw = path.read_bytes()
    try:
        examples = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        for example in examples:
            if not isinstance(example, dict) or not isinstance(example.get("content"), str) or not example["content"]:
                raise ValueError
            if any(type(example.get(label)) is not int or example[label] not in (0, 1) for label in LABELS):
                raise ValueError
        if not examples:
            raise ValueError
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Corpus must contain nonempty JSONL cases with content and binary labels") from exc
    return examples, hashlib.sha256(raw).hexdigest()


async def collect_report(snapshot, examples, corpus_hash, classifier, thresholds, metadata=None, pricing=None):
    start = time.perf_counter()
    started_at = datetime.now(UTC)
    sanitizer = DeterministicSanitizer(snapshot.data["sanitization"]["detectors"])
    cases = []
    for index, example in enumerate(examples, 1):
        if metadata is not None:
            metadata.reset()
        safe = sanitizer.sanitize(example["content"])
        before = time.perf_counter()
        result = await classifier.classify(safe)
        elapsed = (time.perf_counter() - before) * 1000
        scores = result.signals.as_dict()
        cases.append(BenchmarkCase(
            case_id=f"case-{index:04d}",  # Never export corpus IDs or prompt text.
            labels={label: CaseLabel(
                expected=bool(example[label]),
                predicted=thresholds[label].predicts(scores[label]) if result.failure is None else None,
                score=scores[label] if result.failure is None else None,
            ) for label in LABELS},
            failure=result.failure, latency_ms=elapsed,
            reported_model=metadata.model if metadata else None,
            usage=metadata.usage if metadata else None,
        ))
    reported = sorted({case.reported_model for case in cases if case.reported_model})
    dated_snapshot = reported[0] if (
        len(reported) == 1 and re.search(r"-\d{4}-\d{2}-\d{2}$", reported[0])
        and all(case.reported_model == reported[0] for case in cases)
    ) else None
    successful = sum(case.failure is None for case in cases)
    return BenchmarkReport(
        started_at=started_at, completed_at=datetime.now(UTC),
        configured_model=snapshot.data["semantic"]["model"], reported_models=reported,
        model_snapshot=dated_snapshot, policy_version=snapshot.version,
        corpus_sha256=corpus_hash, corpus_size=len(cases), successful=successful,
        failed=len(cases) - successful, coverage=divide(successful, len(cases)),
        thresholds=thresholds, metrics={label: metrics_for(cases, label) for label in LABELS},
        average_latency_ms=sum(case.latency_ms for case in cases) / len(cases) if cases else None,
        total_runtime_ms=(time.perf_counter() - start) * 1000, pricing=pricing,
        estimated_api_cost_usd=estimate_cost(cases, pricing), cases=cases,
    )


async def run(policy_path, schema_path, corpus_path, threshold=None, *, output=None, overrides=None, pricing_path=None):
    snapshot = PolicyStore(policy_path, schema_path).get()
    semantic = snapshot.data["semantic"]
    if semantic["provider"] != "openai" or not semantic.get("model"):
        raise ValueError("Benchmark policy must configure semantic.provider=openai and semantic.model")
    explicit = {label: threshold for label in LABELS} if threshold is not None else {}
    explicit.update(overrides or {})
    thresholds = policy_thresholds(snapshot.data, explicit)
    examples, corpus_hash = load_corpus(corpus_path)
    pricing = Pricing.model_validate_json(pricing_path.read_text()) if pricing_path else None
    if pricing is not None and pricing.model != semantic["model"]:
        raise ValueError("Pricing model must match semantic.model")
    client = None
    metadata = None
    try:
        if os.getenv("OPENAI_API_KEY", "").strip():
            from openai import AsyncOpenAI

            client = AsyncOpenAI(timeout=int(semantic["timeout_ms"]) / 1000, max_retries=0)
            metadata = ResponseMetadata(client.responses)
        classifier = OpenAIResponsesClassifier(
            str(semantic["model"]), int(semantic["timeout_ms"]),
            client=SimpleNamespace(responses=metadata) if metadata else None,
        )
        report = await collect_report(snapshot, examples, corpus_hash, classifier, thresholds, metadata, pricing)
    finally:
        if client is not None:
            await client.close()
    if output is not None:
        write_report(output, report)
    print(report.model_dump_json(indent=2))
    return 0 if report.failed == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline smoke-test benchmark; not production-grade validation")
    parser.add_argument("--policy", type=Path, default=Path(os.getenv("CONTROL_LAYER_POLICY_PATH", ROOT / "policies/example.policy.yaml")))
    parser.add_argument("--schema", type=Path, default=Path(os.getenv("CONTROL_LAYER_POLICY_SCHEMA_PATH", ROOT / "policies/policy.schema.json")))
    parser.add_argument("--corpus", type=Path, default=ROOT / "backend/tests/fixtures/security_corpus.jsonl")
    parser.add_argument("--output", type=Path, default=Path(os.getenv("CONTROL_LAYER_BENCHMARK_PATH", ROOT / "backend/benchmark-results/latest.json")))
    parser.add_argument("--threshold", type=float, help="Explicit >= override for both labels (default: exact policy cutoffs)")
    parser.add_argument("--prompt-injection-threshold", type=float)
    parser.add_argument("--data-exfiltration-threshold", type=float)
    parser.add_argument("--pricing", type=Path, help="Optional model-specific USD-per-million pricing JSON")
    args = parser.parse_args()
    overrides = {label: getattr(args, f"{label}_threshold") for label in LABELS if getattr(args, f"{label}_threshold") is not None}
    try:
        return asyncio.run(run(args.policy, args.schema, args.corpus, args.threshold,
                               output=args.output, overrides=overrides, pricing_path=args.pricing))
    except (OSError, ValueError):
        # Validation exceptions can contain raw input: never print them.
        print("Benchmark configuration/corpus/report invalid or inaccessible; no report published. Check policy cutoffs, explicit overrides, model pricing and file paths.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
