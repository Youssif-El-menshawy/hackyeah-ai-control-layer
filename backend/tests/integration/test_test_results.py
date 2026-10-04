import json
import hashlib

from fastapi.testclient import TestClient

from control_layer.api.app import create_app
from control_layer.api.auth import APIKeyAuthenticator, Principal


URL = "/api/v1/tests/latest"
HEADERS = {"Authorization": "Bearer test-key"}


def client_for(policy_store, repository, authenticator, monkeypatch, path):
    monkeypatch.setenv("CONTROL_LAYER_TEST_RESULTS_PATH", str(path))
    return TestClient(create_app(policy_store=policy_store, repository=repository, authenticator=authenticator))


def test_missing_test_results_are_explicitly_empty(policy_store, repository, authenticator, monkeypatch, tmp_path):
    client = client_for(policy_store, repository, authenticator, monkeypatch, tmp_path / "missing.json")
    response = client.get(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() is None
    assert response.headers["cache-control"] == "no-store"
    assert repository.list_events() == []
    assert client.post(URL, headers=HEADERS).status_code == 405


def test_only_safe_validated_summary_is_exposed(policy_store, repository, authenticator, monkeypatch, tmp_path):
    path = tmp_path / "latest.json"
    summary = {
        "passed": 5, "failed": 1, "skipped": 2, "total": 8,
        "duration_seconds": 1.25, "completed_at": "2026-10-04T12:00:00Z", "status": "failed",
    }
    path.write_text(json.dumps(summary))
    client = client_for(policy_store, repository, authenticator, monkeypatch, path)
    response = client.get(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {**summary, "completed_at": "2026-10-04T12:00:00Z"}
    assert repository.list_events() == []


def test_test_results_require_viewer_scope(policy_store, repository, authenticator, monkeypatch, tmp_path):
    client = client_for(policy_store, repository, authenticator, monkeypatch, tmp_path / "missing.json")
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=HEADERS).status_code == 200
    evaluate_only = APIKeyAuthenticator({hashlib.sha256(b"evaluate-key").hexdigest(): Principal("evaluator", frozenset({"evaluate"}))})
    restricted = client_for(policy_store, repository, evaluate_only, monkeypatch, tmp_path / "missing.json")
    assert restricted.get(URL, headers={"Authorization": "Bearer evaluate-key"}).status_code == 403


def test_invalid_artifact_never_leaks_content(policy_store, repository, authenticator, monkeypatch, tmp_path):
    path = tmp_path / "invalid.json"
    client = client_for(policy_store, repository, authenticator, monkeypatch, path)
    valid = {
        "passed": 5, "failed": 0, "skipped": 0, "total": 5,
        "duration_seconds": 1.25, "completed_at": "2026-10-04T12:00:00Z", "status": "passed",
    }
    for payload in (
        {**valid, "raw_log": "private@example.com"},
        {**valid, "total": 6},
        {**valid, "failed": 1},
        {**valid, "duration_seconds": -1},
        {**valid, "completed_at": "2026-10-04T12:00:00"},
    ):
        path.write_text(json.dumps(payload))
        response = client.get(URL, headers=HEADERS)
        assert response.status_code == 503
        assert "private@example.com" not in response.text
        assert "raw_log" not in response.text
