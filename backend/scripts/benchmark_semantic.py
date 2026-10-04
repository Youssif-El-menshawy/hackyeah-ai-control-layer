from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from control_layer.core.detectors import DeterministicSanitizer
from control_layer.policy.loader import PolicyStore
from control_layer.semantic.openai_adapter import OpenAIResponsesClassifier


async def run(policy_path: Path, schema_path: Path, corpus_path: Path, threshold: float) -> int:
    snapshot = PolicyStore(policy_path, schema_path).get()
    semantic = snapshot.data["semantic"]
    if semantic["provider"] != "openai" or not semantic.get("model"):
        raise SystemExit("Benchmark policy must configure semantic.provider=openai and semantic.model")
    classifier = OpenAIResponsesClassifier(str(semantic["model"]), int(semantic["timeout_ms"]))
    sanitizer = DeterministicSanitizer(snapshot.data["sanitization"]["detectors"])
    examples = [json.loads(line) for line in corpus_path.read_text().splitlines() if line.strip()]
    outcomes: dict[str, list[tuple[int, int]]] = {"prompt_injection": [], "data_exfiltration": []}
    latencies: list[float] = []

    for example in examples:
        safe = sanitizer.sanitize(example["content"])
        started = time.perf_counter()
        result = await classifier.classify(safe)
        latencies.append((time.perf_counter() - started) * 1000)
        if result.failure:
            print(json.dumps({"id": example["id"], "failure": result.failure.value}))
            continue
        for label, score in result.signals.as_dict().items():
            outcomes[label].append((int(example[label]), int(score >= threshold)))

    report = {"configured_model": semantic["model"], "threshold": threshold, "examples": len(examples)}
    for label, pairs in outcomes.items():
        tp = sum(expected == predicted == 1 for expected, predicted in pairs)
        fp = sum(expected == 0 and predicted == 1 for expected, predicted in pairs)
        fn = sum(expected == 1 and predicted == 0 for expected, predicted in pairs)
        report[label] = {
            "precision": tp / (tp + fp) if tp + fp else 0,
            "recall": tp / (tp + fn) if tp + fn else 0,
            "evaluated": len(pairs),
        }
    report["latency_ms"] = {
        "mean": round(statistics.mean(latencies), 1) if latencies else None,
        "p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 1) if latencies else None,
    }
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the configured semantic model on a labeled corpus")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.65)
    args = parser.parse_args()
    return asyncio.run(run(args.policy, args.schema, args.corpus, args.threshold))


if __name__ == "__main__":
    raise SystemExit(main())
