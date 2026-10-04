import asyncio
import json
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from control_layer.benchmark import (
    LABELS, BenchmarkCase, BenchmarkReport, CaseLabel, Pricing, TokenUsage,
    estimate_cost, metrics_for, policy_thresholds, write_report,
)
from control_layer.core.types import FailureKind, RiskSignals, SemanticResult


def case(expected, predicted):
    return BenchmarkCase(case_id="case-1", labels={label: CaseLabel(
        expected=expected, predicted=predicted, score=float(predicted)
    ) for label in LABELS}, failure=None, latency_ms=1)


def test_metrics_include_each_confusion_outcome_and_correct_denominators():
    cases = [case(True, True)] * 2 + [case(False, False)] * 3 + [case(False, True)] + [case(True, False)] * 2
    metrics = metrics_for(cases, "prompt_injection")
    assert (metrics.tp, metrics.tn, metrics.fp, metrics.fn) == (2, 3, 1, 2)
    assert metrics.evaluated == 8
    assert metrics.accuracy == 5 / 8
    assert metrics.precision == 2 / 3
    assert metrics.recall == 2 / 4
    assert metrics.f1 == 4 / 7
    assert metrics.false_positive_rate == 1 / 4
    assert metrics.false_negative_rate == 2 / 4


def test_undefined_metrics_are_null_not_zero():
    assert all(value is None for key, value in metrics_for([], "prompt_injection").model_dump().items()
               if key not in ("evaluated", "tp", "tn", "fp", "fn"))
    metric = metrics_for([case(False, False)], "prompt_injection")
    assert metric.accuracy == 1
    assert metric.precision is metric.recall is metric.f1 is metric.false_negative_rate is None
    assert metric.false_positive_rate == 0


def test_exact_per_label_policy_thresholds_and_overrides(policy_store):
    policy = yaml.safe_load(policy_store.policy_path.read_text())
    thresholds = policy_thresholds(policy)
    assert thresholds["prompt_injection"].value == 0.65
    assert thresholds["data_exfiltration"].value == 0.8
    assert thresholds["data_exfiltration"].predicts(0.8)
    rule = next(r for r in policy["decision_rules"] if r["id"] == "high-exfiltration-risk")
    rule["when"]["all"][0].update(value=0.71234, operator="gt")
    thresholds = policy_thresholds(policy, {"prompt_injection": 0.25})
    assert thresholds["prompt_injection"].source == "override"
    assert thresholds["prompt_injection"].value == 0.25
    assert thresholds["data_exfiltration"].value == 0.71234
    assert not thresholds["data_exfiltration"].predicts(0.71234)
    assert thresholds["data_exfiltration"].predicts(0.71235)


@pytest.mark.parametrize("change", ["missing", "compound", "ambiguous", "disabled", "unsupported"])
def test_threshold_resolution_never_silently_guesses(policy_store, change):
    policy = yaml.safe_load(policy_store.policy_path.read_text())
    rule = next(r for r in policy["decision_rules"] if r["id"] == "high-exfiltration-risk")
    if change == "missing":
        policy["decision_rules"].remove(rule)
    elif change == "compound":
        rule["when"]["all"].append({"fact": "model.allowed", "operator": "eq", "value": True})
    elif change == "ambiguous":
        other = json.loads(json.dumps(rule))
        other["when"]["all"][0]["value"] = 0.9
        policy["decision_rules"].append(other)
    elif change == "disabled":
        policy["semantic"]["labels"]["data_exfiltration"]["enabled"] = False
    else:
        rule["when"]["all"][0]["operator"] = "eq"
    with pytest.raises(ValueError):
        policy_thresholds(policy)
    assert policy_thresholds(policy, {"data_exfiltration": 0.7})["data_exfiltration"].source == "override"


@pytest.mark.parametrize("threshold", [-1, 1.1, float("nan"), float("inf")])
def test_invalid_override_rejected(policy_store, threshold):
    with pytest.raises(ValueError):
        policy_thresholds(policy_store.get().data, {"prompt_injection": threshold})


@pytest.mark.parametrize("failure", list(FailureKind))
def test_failures_count_toward_coverage_not_safe_predictions(policy_store, benchmark_runner, failure):
    class Classifier:
        async def classify(self, content):
            return SemanticResult(failure=failure)

    snapshot = policy_store.get()
    report = asyncio.run(benchmark_runner.collect_report(snapshot, [
        {"content": "hello", "prompt_injection": 1, "data_exfiltration": 1}
    ], "a" * 64, Classifier(), policy_thresholds(snapshot.data)))
    assert (report.corpus_size, report.successful, report.failed, report.coverage) == (1, 0, 1, 0)
    assert report.cases[0].labels["prompt_injection"].predicted is None
    assert report.metrics["prompt_injection"].evaluated == 0
    assert report.metrics["prompt_injection"].accuracy is None
    assert report.estimated_api_cost_usd is report.model_snapshot is None


def test_mixed_results_preserve_privacy_sanitization_and_coverage(policy_store, benchmark_runner):
    class Classifier:
        received = []

        async def classify(self, content):
            self.received.append(content.value)
            return SemanticResult(RiskSignals(0.65, 0.79)) if len(self.received) == 1 else SemanticResult(failure=FailureKind.TIMEOUT)

    spy = Classifier()
    snapshot = policy_store.get()
    examples = [{"id": "SECRET-ID", "content": "john@example.com. password=hunter22", "prompt_injection": 1, "data_exfiltration": 0}] * 2
    report = asyncio.run(benchmark_runner.collect_report(snapshot, examples, "a" * 64, spy, policy_thresholds(snapshot.data)))
    assert report.coverage == 0.5
    assert report.successful == report.failed == 1
    assert report.metrics["prompt_injection"].tp == 1
    assert report.metrics["data_exfiltration"].tn == 1
    for forbidden in ("john@example.com", "hunter22", "SECRET-ID", "REDACTED"):
        assert forbidden not in report.model_dump_json()
    assert all("john@example.com" not in content and "hunter22" not in content for content in spy.received)
    assert "[REDACTED_EMAIL_1]" in spy.received[0]


def test_cost_requires_complete_model_specific_pricing_and_usage():
    item = case(False, False)
    item.usage = TokenUsage(input_tokens=100, output_tokens=20, cached_input_tokens=30)
    pricing = Pricing(model="test-model", input_usd_per_million=2, output_usd_per_million=8, cached_input_usd_per_million=1)
    assert estimate_cost([item], pricing) == pytest.approx(0.00033)
    assert estimate_cost([item], None) is None
    assert estimate_cost([item, case(False, False)], pricing) is None
    pricing.cached_input_usd_per_million = None
    assert estimate_cost([item], pricing) is None
    item.usage.cache_write_tokens = 5
    assert estimate_cost([item], pricing) is None


def test_metadata_wrapper_uses_real_adapter_without_retaining_text(benchmark_runner):
    from control_layer.core.types import SanitizedContent
    from control_layer.semantic.openai_adapter import OpenAIResponsesClassifier

    class Responses:
        async def create(self, **kwargs):
            assert kwargs["store"] is False
            assert kwargs["model"] == "test-model"
            return SimpleNamespace(model="test-model-2026-01-01", output_text='{"prompt_injection":0.1,"data_exfiltration":0.2}',
                usage=SimpleNamespace(input_tokens=10, output_tokens=5, input_tokens_details=SimpleNamespace(cached_tokens=0)))

    metadata = benchmark_runner.ResponseMetadata(Responses())
    adapter = OpenAIResponsesClassifier("test-model", 1000, client=SimpleNamespace(responses=metadata))
    result = asyncio.run(adapter.classify(SanitizedContent("safe")))
    assert result.failure is None
    assert metadata.model == "test-model-2026-01-01"
    assert metadata.usage.input_tokens == 10
    assert not hasattr(metadata, "output_text")
    metadata.reset()
    assert metadata.model is metadata.usage is None


def test_atomic_report_roundtrip_and_validation(benchmark_report, tmp_path):
    target = tmp_path / "reports/latest.json"
    write_report(target, benchmark_report)
    assert BenchmarkReport.model_validate_json(target.read_bytes()) == benchmark_report
    assert list(target.parent.iterdir()) == [target]
    for mutate in (lambda d: d.update(coverage=0.5), lambda d: d.update(content="secret"),
                   lambda d: d["metrics"]["prompt_injection"].update(tp=999),
                   lambda d: d["cases"][0].update(case_id="private@example.com")):
        data = benchmark_report.model_dump(mode="json")
        mutate(data)
        with pytest.raises(ValidationError):
            BenchmarkReport.model_validate(data)


@pytest.mark.parametrize("content", ["", "not json", '{"content":"private", "prompt_injection":2,"data_exfiltration":0}'])
def test_invalid_corpus_rejected_before_calls(benchmark_runner, tmp_path, content):
    path = tmp_path / "corpus.jsonl"
    path.write_text(content)
    with pytest.raises(ValueError, match="Corpus must contain"):
        benchmark_runner.load_corpus(path)


def test_runner_emits_one_json_document_and_real_failure_report(policy_store, benchmark_runner, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps({"id":"secret", "content":"hello", "prompt_injection":0,"data_exfiltration":0}))
    output = tmp_path / "latest.json"
    code = asyncio.run(benchmark_runner.run(policy_store.policy_path, policy_store.schema_path, corpus, output=output))
    report = json.loads(capsys.readouterr().out)
    assert code == 2
    assert json.loads(output.read_text()) == report
    assert report["benchmark_kind"] == "smoke-test"
    assert report["coverage"] == 0
    assert report["cases"][0]["failure"] == "outage"
    assert report["thresholds"]["data_exfiltration"]["value"] == 0.8


@pytest.mark.parametrize("reported_model", ["candidate-alias", "candidate-2026-01-01", None])
def test_successful_runner_captures_snapshot_usage_and_closes_client(
    policy_store, benchmark_runner, tmp_path, monkeypatch, capsys, reported_model
):
    import openai

    class Client:
        closed = False
        responses = None

        def __init__(self, **kwargs):
            self.responses = self
            assert kwargs["max_retries"] == 0

        async def create(self, **kwargs):
            assert "john@example.com" not in kwargs["input"][1]["content"]
            assert kwargs["store"] is False
            return SimpleNamespace(model=reported_model, output_text='{"prompt_injection":0.65,"data_exfiltration":0.8}',
                usage=SimpleNamespace(input_tokens=100, output_tokens=20, input_tokens_details=SimpleNamespace(cached_tokens=0)))

        async def close(self):
            Client.closed = True

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setattr(openai, "AsyncOpenAI", Client)
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps({"content":"john@example.com.","prompt_injection":1,"data_exfiltration":1}))
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"model":policy_store.get().data["semantic"]["model"],
        "input_usd_per_million":2,"output_usd_per_million":8}))
    code = asyncio.run(benchmark_runner.run(policy_store.policy_path, policy_store.schema_path, corpus, pricing_path=pricing))
    report = BenchmarkReport.model_validate_json(capsys.readouterr().out)
    assert code == 0
    assert Client.closed
    assert report.coverage == 1
    assert report.model_snapshot == (reported_model if reported_model == "candidate-2026-01-01" else None)
    assert report.estimated_api_cost_usd == pytest.approx(0.00036)
    assert report.metrics["prompt_injection"].tp == report.metrics["data_exfiltration"].tp == 1


def test_cli_bad_configuration_has_no_raw_error_or_fake_report(benchmark_runner, tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "invalid.jsonl"
    corpus.write_text('{"content":"private@example.com"}')
    target = tmp_path / "latest.json"
    monkeypatch.setattr("sys.argv", ["benchmark_semantic.py", "--corpus", str(corpus), "--output", str(target)])
    assert benchmark_runner.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private@example.com" not in captured.err
    assert not target.exists()
