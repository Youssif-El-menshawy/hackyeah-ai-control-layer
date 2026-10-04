from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from control_layer.api.auth import APIKeyAuthenticator, Principal
from control_layer.policy.loader import PolicyStore
from control_layer.storage.sqlite import SQLiteRepository


WORKSPACE = Path(__file__).resolve().parents[2]
_RUN_RESULTS: dict[str, str] = {}
_COLLECTION_ERRORS: set[str] = set()
_RUN_STARTED = 0.0


def pytest_sessionstart(session):
    global _RUN_STARTED
    _RUN_STARTED = time.perf_counter()
    _RUN_RESULTS.clear()
    _COLLECTION_ERRORS.clear()


def pytest_runtest_logreport(report):
    current = _RUN_RESULTS.get(report.nodeid)
    if report.failed:
        _RUN_RESULTS[report.nodeid] = "failed"
    elif report.skipped and current != "failed":
        _RUN_RESULTS[report.nodeid] = "skipped"
    elif report.when == "call" and report.passed and current is None:
        _RUN_RESULTS[report.nodeid] = "passed"


def pytest_collectreport(report):
    if report.failed:
        _COLLECTION_ERRORS.add(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    if session.config.option.collectonly:
        return
    from control_layer.api.test_results import TestRunSummary

    passed = sum(value == "passed" for value in _RUN_RESULTS.values())
    failed = sum(value == "failed" for value in _RUN_RESULTS.values()) + len(_COLLECTION_ERRORS)
    skipped = sum(value == "skipped" for value in _RUN_RESULTS.values())
    total = passed + failed + skipped
    summary = TestRunSummary(
        passed=passed, failed=failed, skipped=skipped, total=total,
        duration_seconds=time.perf_counter() - _RUN_STARTED,
        completed_at=datetime.now(UTC),
        status="failed" if failed else "incomplete" if exitstatus != 0 or total == 0 else "passed",
    )
    destination = Path(os.getenv("CONTROL_LAYER_TEST_RESULTS_PATH", WORKSPACE / "backend/latest_test_results.json"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(summary.model_dump(mode="json"), stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@pytest.fixture
def policy_store(tmp_path: Path) -> PolicyStore:
    policy = tmp_path / "policy.yaml"
    policy.write_text((WORKSPACE / "policies/example.policy.yaml").read_text(), encoding="utf-8")
    return PolicyStore(policy, WORKSPACE / "policies/policy.schema.json")


@pytest.fixture
def repository(tmp_path: Path) -> SQLiteRepository:
    return SQLiteRepository(tmp_path / "test.sqlite3")


@pytest.fixture
def authenticator() -> APIKeyAuthenticator:
    key = "test-key"
    digest = hashlib.sha256(key.encode()).hexdigest()
    principal = Principal("pytest", frozenset({"evaluate", "viewer", "approver", "admin"}))
    return APIKeyAuthenticator({digest: principal})


@pytest.fixture(scope="session")
def benchmark_runner():
    spec = importlib.util.spec_from_file_location("benchmark_semantic", WORKSPACE / "backend/scripts/benchmark_semantic.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def benchmark_report(policy_store, benchmark_runner):
    import asyncio

    from control_layer.benchmark import policy_thresholds
    from control_layer.semantic.stub import StubSemanticClassifier

    snapshot = policy_store.get()
    return asyncio.run(benchmark_runner.collect_report(
        snapshot,
        [{"id": "private@example.com", "content": "Contact private@example.com.", "prompt_injection": 0, "data_exfiltration": 0}],
        "a" * 64, StubSemanticClassifier(), policy_thresholds(snapshot.data),
    ))
