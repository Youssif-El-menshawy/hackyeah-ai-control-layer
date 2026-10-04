import hashlib

from fastapi.testclient import TestClient

from control_layer.api.app import create_app
from control_layer.api.auth import APIKeyAuthenticator, Principal
from control_layer.benchmark import write_report


def client_for(policy_store, repository, monkeypatch, path, scopes=("viewer",)):
    monkeypatch.setenv("CONTROL_LAYER_BENCHMARK_PATH", str(path))
    auth = APIKeyAuthenticator({hashlib.sha256(b"viewer-key").hexdigest(): Principal("viewer", frozenset(scopes))})
    return TestClient(create_app(policy_store=policy_store, repository=repository, authenticator=auth))


HEADERS = {"Authorization": "Bearer viewer-key"}
URL = "/api/v1/benchmarks/latest"


def test_missing_report_is_explicit_null(policy_store, repository, monkeypatch, tmp_path):
    client = client_for(policy_store, repository, monkeypatch, tmp_path / "absent.json")
    response = client.get(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() is None
    assert response.headers["cache-control"] == "no-store"
    assert repository.list_events() == []


def test_report_read_is_authorized_safe_and_does_not_evaluate(policy_store, repository, benchmark_report, monkeypatch, tmp_path):
    path = tmp_path / "latest.json"
    write_report(path, benchmark_report)
    client = client_for(policy_store, repository, monkeypatch, path)
    response = client.get(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == benchmark_report.model_dump(mode="json")
    assert "private@example.com" not in response.text
    assert "content" not in response.json()
    assert repository.list_events() == []
    assert client.post(URL, headers=HEADERS).status_code == 405


def test_report_requires_viewer_or_admin(policy_store, repository, monkeypatch, tmp_path):
    path = tmp_path / "missing.json"
    client = client_for(policy_store, repository, monkeypatch, path, ("evaluate",))
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=HEADERS).status_code == 403
    client = client_for(policy_store, repository, monkeypatch, path, ("admin",))
    assert client.get(URL, headers=HEADERS).status_code == 200


def test_invalid_report_is_not_empty_state_and_does_not_leak_validation_input(policy_store, repository, monkeypatch, tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"content":"private@example.com", "api_key":"do-not-leak"}')
    client = client_for(policy_store, repository, monkeypatch, path)
    response = client.get(URL, headers=HEADERS)
    assert response.status_code == 503
    assert "private@example.com" not in response.text
    assert "do-not-leak" not in response.text
