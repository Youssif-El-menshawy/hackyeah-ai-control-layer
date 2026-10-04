"""Offline benchmark reports; never used by the evaluation service."""
from __future__ import annotations

import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from control_layer.core.types import FailureKind

LABELS = ("prompt_injection", "data_exfiltration")
Label = Literal["prompt_injection", "data_exfiltration"]
Rate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0, strict=True)]
ModelName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class SafeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Threshold(SafeModel):
    value: Rate
    operator: Literal["gte", "gt"] = "gte"
    source: Literal["policy", "override"]

    def predicts(self, score: float) -> bool:
        return score >= self.value if self.operator == "gte" else score > self.value


class CaseLabel(SafeModel):
    expected: bool
    predicted: bool | None
    score: Rate | None


class TokenUsage(SafeModel):
    input_tokens: Count
    output_tokens: Count
    cached_input_tokens: Count
    cache_write_tokens: Count = 0

    @model_validator(mode="after")
    def valid_cache(self):
        if self.cached_input_tokens + self.cache_write_tokens > self.input_tokens:
            raise ValueError("Invalid token usage")
        return self


class BenchmarkCase(SafeModel):
    case_id: str = Field(pattern=r"^case-[0-9]+$")
    labels: dict[Label, CaseLabel]
    latency_ms: Nonnegative
    failure: FailureKind | None
    reported_model: ModelName | None = None
    usage: TokenUsage | None = None

    @model_validator(mode="after")
    def valid_labels(self):
        if set(self.labels) != set(LABELS):
            raise ValueError("Both labels are required")
        for item in self.labels.values():
            if self.failure is None:
                if item.score is None or item.predicted is None:
                    raise ValueError("Successful cases require scores and predictions")
            elif item.score is not None or item.predicted is not None:
                raise ValueError("Failed cases must not contain predictions")
        return self


class Metrics(SafeModel):
    evaluated: Count
    tp: Count
    tn: Count
    fp: Count
    fn: Count
    accuracy: Rate | None
    precision: Rate | None
    recall: Rate | None
    f1: Rate | None
    false_positive_rate: Rate | None
    false_negative_rate: Rate | None


def divide(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def metrics_for(cases: list[BenchmarkCase], label: str) -> Metrics:
    pairs = [case.labels[label] for case in cases if case.failure is None]
    tp = sum(item.expected and item.predicted is True for item in pairs)
    tn = sum(not item.expected and item.predicted is False for item in pairs)
    fp = sum(not item.expected and item.predicted is True for item in pairs)
    fn = sum(item.expected and item.predicted is False for item in pairs)
    return Metrics(
        evaluated=len(pairs), tp=tp, tn=tn, fp=fp, fn=fn,
        accuracy=divide(tp + tn, len(pairs)), precision=divide(tp, tp + fp),
        recall=divide(tp, tp + fn), f1=divide(2 * tp, 2 * tp + fp + fn),
        false_positive_rate=divide(fp, fp + tn), false_negative_rate=divide(fn, fn + tp),
    )


class Pricing(SafeModel):
    model: ModelName
    input_usd_per_million: Nonnegative
    output_usd_per_million: Nonnegative
    cached_input_usd_per_million: Nonnegative | None = None


def estimate_cost(cases: list[BenchmarkCase], pricing: Pricing | None) -> float | None:
    if not cases or pricing is None:
        return None
    total = 0.0
    for case in cases:
        usage = case.usage
        if usage is None or usage.cache_write_tokens:
            return None
        if usage.cached_input_tokens and pricing.cached_input_usd_per_million is None:
            return None
        total += (
            (usage.input_tokens - usage.cached_input_tokens) * pricing.input_usd_per_million
            + usage.output_tokens * pricing.output_usd_per_million
            + usage.cached_input_tokens * (pricing.cached_input_usd_per_million or 0)
        ) / 1_000_000
    return total


class BenchmarkReport(SafeModel):
    schema_version: Literal["1.0"] = "1.0"
    benchmark_kind: Literal["smoke-test"] = "smoke-test"
    started_at: datetime
    completed_at: datetime
    configured_model: ModelName
    reported_models: list[ModelName]
    model_snapshot: ModelName | None
    policy_version: Digest
    corpus_sha256: Digest
    corpus_size: Count
    successful: Count
    failed: Count
    coverage: Rate | None
    thresholds: dict[Label, Threshold]
    metrics: dict[Label, Metrics]
    average_latency_ms: Nonnegative | None
    total_runtime_ms: Nonnegative
    pricing: Pricing | None = None
    estimated_api_cost_usd: Nonnegative | None
    cases: list[BenchmarkCase]

    @model_validator(mode="after")
    def consistent_report(self):
        if self.started_at.utcoffset() is None or self.completed_at.utcoffset() is None:
            raise ValueError("Benchmark timestamps must include timezone")
        if self.completed_at < self.started_at:
            raise ValueError("Invalid benchmark timestamps")
        if set(self.thresholds) != set(LABELS) or set(self.metrics) != set(LABELS):
            raise ValueError("Both labels are required")
        count = len(self.cases)
        successful = sum(case.failure is None for case in self.cases)
        if (self.corpus_size, self.successful, self.failed, self.coverage) != (
            count, successful, count - successful, divide(successful, count)
        ):
            raise ValueError("Inconsistent benchmark coverage")
        if len({case.case_id for case in self.cases}) != count:
            raise ValueError("Duplicate benchmark case")
        for label in LABELS:
            if self.metrics[label] != metrics_for(self.cases, label):
                raise ValueError("Inconsistent benchmark metrics")
            for case in self.cases:
                item = case.labels[label]
                if item.score is not None and item.predicted != self.thresholds[label].predicts(item.score):
                    raise ValueError("Prediction does not match threshold")
        if self.reported_models != sorted({case.reported_model for case in self.cases if case.reported_model}):
            raise ValueError("Inconsistent reported model metadata")
        if self.model_snapshot is not None and (
            not re.search(r"-\d{4}-\d{2}-\d{2}$", self.model_snapshot)
            or any(case.reported_model != self.model_snapshot for case in self.cases)
            or self.reported_models != [self.model_snapshot]
        ):
            raise ValueError("Snapshot must be a dated model reported for every case")
        if self.pricing is not None and self.pricing.model != self.configured_model:
            raise ValueError("Pricing must match configured model")
        if self.estimated_api_cost_usd != estimate_cost(self.cases, self.pricing):
            raise ValueError("Inconsistent estimated cost")
        average = sum(case.latency_ms for case in self.cases) / count if count else None
        if (average is None) != (self.average_latency_ms is None) or (
            average is not None and not math.isclose(average, self.average_latency_ms)
        ):
            raise ValueError("Inconsistent average latency")
        return self


def policy_thresholds(policy, overrides: dict[str, float] | None = None) -> dict[str, Threshold]:
    """Refuse to guess when policy logic cannot map to one binary cutoff."""
    overrides = overrides or {}
    result = {}
    for label in LABELS:
        if label in overrides:
            result[label] = Threshold(value=overrides[label], source="override")
            continue
        candidates = []
        for rule in policy["decision_rules"]:
            conditions = rule["when"].get("all", rule["when"].get("any", ()))
            for item in conditions:
                if item["fact"] == f"semantic.{label}":
                    if len(conditions) != 1 or item["operator"] not in ("gte", "gt"):
                        raise ValueError(f"Ambiguous policy threshold for {label}; supply an explicit override")
                    candidates.append((item["operator"], float(item["value"])))
        if len(set(candidates)) != 1 or not policy["semantic"]["labels"][label]["enabled"]:
            raise ValueError(f"Missing, disabled or ambiguous policy threshold for {label}; supply an explicit override")
        operator, value = candidates[0]
        result[label] = Threshold(value=value, operator=operator, source="policy")
    return result


def write_report(path: Path, report: BenchmarkReport) -> None:
    """Publish atomically so the endpoint never reads a partial report."""
    payload = report.model_dump_json(indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
