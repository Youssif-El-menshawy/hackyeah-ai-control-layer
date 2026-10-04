from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from control_layer.api.app import create_app


def evaluate(client, input):
    response = client.post(
        "/api/v1/evaluations",
        headers={"Authorization": "Bearer test-key"},
        json={
            "request_id": str(uuid4()),
            "agent_id": "support-agent",
            "model": "approved-model-small",
            "input": input,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def assert_startup(client):
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger-ui" in docs.text
    assert client.get("/openapi.json").status_code == 200
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_stub_factory_works_without_openai_key(policy_store, repository, authenticator, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    policy = yaml.safe_load(policy_store.policy_path.read_text())
    policy["semantic"]["provider"] = "stub"
    policy_store.policy_path.write_text(yaml.safe_dump(policy))
    policy_store.reload()
    app = create_app(policy_store=policy_store, repository=repository, authenticator=authenticator)
    with TestClient(app) as client:
        assert_startup(client)
        for content, expected in (
            ("Hello", "ALLOW"),
            ("Contact person@example.com", "REDACT"),
            ("password=sample-secret-value", "BLOCK"),
        ):
            result = evaluate(client, {"type": "prompt", "content": content})
            assert result["decision"] == expected
            if expected == "REDACT":
                assert "person@example.com" not in result["sanitized_content"]


@pytest.mark.parametrize("credential", [None, "", "   "])
@pytest.mark.parametrize("prompt_fallback", ["REQUIRE_APPROVAL", "BLOCK"])
def test_missing_openai_credentials_follow_policy(
    policy_store, repository, authenticator, monkeypatch, credential, prompt_fallback
):
    if credential is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", credential)

    # No client or classifier mock: exercise the real provider selection path.
    policy = yaml.safe_load(policy_store.policy_path.read_text())
    policy["semantic"]["provider"] = "openai"
    policy["semantic"]["model"] = "test-configured-model"
    policy["semantic"]["failure_policy"]["prompt_actions"]["outage"] = prompt_fallback
    policy_store.policy_path.write_text(yaml.safe_dump(policy))
    policy_store.reload()

    app = create_app(policy_store=policy_store, repository=repository, authenticator=authenticator)
    with TestClient(app) as client:
        assert_startup(client)
        prompt = evaluate(client, {"type": "prompt", "content": "Hello"})
        assert prompt["decision"] == prompt_fallback
        assert prompt["reason_codes"] == ["SEMANTIC_OUTAGE"]
        assert bool(prompt["approval_id"]) == (prompt_fallback == "REQUIRE_APPROVAL")

        tool = evaluate(client, {"type": "tool_call", "tool_name": "create_ticket", "arguments": {}})
        assert tool["decision"] == "BLOCK"
        assert tool["reason_codes"] == ["SEMANTIC_OUTAGE"]

        secret = evaluate(client, {"type": "prompt", "content": "password=sample-secret-value"})
        assert secret["decision"] == "BLOCK"
        assert secret["reason_codes"] == ["DETERMINISTIC_CONTROL_FAILED"]
        assert all(event["semantic_failure"] == "outage" for event in repository.list_events())
