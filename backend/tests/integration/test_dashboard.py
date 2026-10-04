import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from control_layer.api.app import create_app
from control_layer.api.auth import APIKeyAuthenticator, Principal


def client_for(policy_store, repository, scopes=("viewer",)):
    authenticator = APIKeyAuthenticator({hashlib.sha256(b"read-key").hexdigest(): Principal("reader", frozenset(scopes))})
    return TestClient(create_app(policy_store=policy_store, repository=repository, authenticator=authenticator))


HEADERS = {"Authorization": "Bearer read-key"}


def add_event(repository, policy_store, index=0, **changes):
    event = {
        "evaluation_id": str(uuid4()), "request_id": str(uuid4()), "agent_id": "support-agent",
        "model": "approved-model-small", "input_type": "prompt", "tool_name": None,
        "decision": "ALLOW", "reason_codes": ["POLICY_ALLOWED"], "policy_version": policy_store.get().version,
        "input_sha256": "a" * 64, "redactions": [],
        "risk_signals": [{"label": "prompt_injection", "score": 0.1}, {"label": "data_exfiltration", "score": 0.2}],
        "semantic_failure": None, "estimated_input_tokens": 5, "latency_ms": 10 + index,
        "created_at": (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index)).isoformat(),
    }
    event.update(changes)
    repository.append_event(event)
    return event


def test_cursor_pages_have_no_duplicates_with_new_events(policy_store, repository):
    original = [add_event(repository, policy_store, i) for i in range(30)]
    client = client_for(policy_store, repository)
    first = client.get("/api/v1/events?limit=12", headers=HEADERS).json()
    add_event(repository, policy_store, 31)
    pages = [first]
    while pages[-1]["next_cursor"]:
        pages.append(client.get("/api/v1/events", headers=HEADERS, params={"limit":12,"cursor":pages[-1]["next_cursor"]}).json())
    ids = [event["evaluation_id"] for page in pages for event in page["items"]]
    assert len(ids) == len(set(ids)) == 30
    assert ids == [event["evaluation_id"] for event in reversed(original)]


def test_filters_and_literal_search_are_combined_and_parameterized(policy_store, repository):
    add_event(repository, policy_store)
    target = add_event(repository, policy_store, 1, decision="BLOCK", reason_codes=["DETERMINISTIC_CONTROL_FAILED"],
                       agent_id="coding-agent", input_type="tool_call", tool_name="execute_shell")
    client = client_for(policy_store, repository)
    response = client.get("/api/v1/events", headers=HEADERS, params={"decision":"BLOCK", "agent_id":"coding-agent", "input_type":"tool_call", "search":"deterministic_control"})
    assert response.json()["items"] == [target]
    assert client.get("/api/v1/events", headers=HEADERS, params={"search":target["request_id"]}).json()["items"] == [target]
    for search in ("%", "' OR 1=1 --"):
        assert client.get("/api/v1/events", headers=HEADERS, params={"search":search}).json()["items"] == []
    assert client.get("/api/v1/events?input_type=invalid", headers=HEADERS).status_code == 422
    for payload in ([42, 42], ["invalid", "invalid"], {"secret": "not echoed"}):
        cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        result = client.get("/api/v1/events", headers=HEADERS, params={"cursor":cursor})
        assert result.status_code == 400
        assert "not echoed" not in result.text


def test_live_overview_is_bounded_and_does_not_invent_denial_facts(policy_store, repository):
    for i in range(105):
        add_event(repository, policy_store, i)
    latest = add_event(repository, policy_store, 106, decision="BLOCK", reason_codes=["DETERMINISTIC_CONTROL_FAILED"],
                       redactions=[{"kind":"secret","count":1}], semantic_failure="outage")
    client = client_for(policy_store, repository)
    result = client.get("/api/v1/dashboard/overview", headers=HEADERS).json()
    assert result["sample_size"] == result["sample_limit"] == 100
    assert result["counts"]["ALLOW"] == 99
    assert result["activity"]["sensitive_data"] == result["activity"]["provider_failures"] == 1
    assert result["activity"]["unauthorized_tools"] is result["activity"]["budget_violations"] is None
    assert result["latest_semantic"] == {"created_at": latest["created_at"], "failure": "outage"}
    assert not result["can_approve"] and not result["can_reload"]
    assert len(repository.list_events(200)) == 106
    assert repository.current_budget_usage(3600) == []


def test_policy_summary_uses_live_snapshot_not_modified_disk(policy_store, repository):
    client = client_for(policy_store, repository)
    snapshot = policy_store.get()
    original = policy_store.policy_path.read_text()
    policy_store.policy_path.write_text("invalid: true")
    result = client.get("/api/v1/policies/overview", headers=HEADERS)
    assert result.status_code == 200
    data = result.json()
    assert data["policy_version"] == snapshot.version
    assert data["semantic_model"] == snapshot.data["semantic"]["model"]
    assert {item["value"] for item in data["thresholds"]} == {0.65, 0.8}
    assert data["enabled_detectors"] == ["email", "phone", "api_key", "secret"]
    assert "patterns" not in result.text and "OPENAI_API_KEY" not in result.text
    policy_store.policy_path.write_text(original)


def test_event_detail_and_pending_queue_are_read_only_and_scoped(policy_store, repository):
    event = add_event(repository, policy_store)
    approval = repository.create_approval(event["evaluation_id"], event["created_at"])
    other = add_event(repository, policy_store, 1)
    resolved = repository.create_approval(other["evaluation_id"], other["created_at"])
    repository.resolve_approval(resolved, "DENIED", "test", None, other["created_at"])
    client = client_for(policy_store, repository, ("viewer", "approver"))
    detail = client.get(f'/api/v1/events/{event["evaluation_id"]}', headers=HEADERS)
    assert detail.json() == event
    assert "content" not in detail.json()
    queue = client.get("/api/v1/approvals?status=PENDING&limit=12", headers=HEADERS).json()
    assert [item["approval_id"] for item in queue] == [approval]
    assert len(client.get("/api/v1/approvals", headers=HEADERS).json()) == 2
    assert client.get("/api/v1/approvals?status=PENDING&offset=1", headers=HEADERS).json() == []
    assert client.get("/api/v1/dashboard/overview", headers=HEADERS).json()["pending_approvals"] == 1
    assert client.get(f"/api/v1/events/{uuid4()}", headers=HEADERS).status_code == 404
    for url in ("/api/v1/policies/overview", "/api/v1/dashboard/overview", f'/api/v1/events/{event["evaluation_id"]}'):
        assert client.get(url).status_code == 401
        restricted = client_for(policy_store, repository, ("evaluate",))
        assert restricted.get(url, headers=HEADERS).status_code == 403
    assert client_for(policy_store, repository).get("/api/v1/approvals", headers=HEADERS).status_code == 403


def test_existing_approval_action_updates_read_only_counts_immediately(policy_store, repository):
    event = add_event(repository, policy_store, decision="REQUIRE_APPROVAL", reason_codes=["PROMPT_INJECTION_REVIEW"])
    approval = repository.create_approval(event["evaluation_id"], event["created_at"])
    client = client_for(policy_store, repository, ("viewer", "approver"))
    assert client.get("/api/v1/dashboard/overview", headers=HEADERS).json()["pending_approvals"] == 1
    assert client.post(f"/api/v1/approvals/{approval}/resolution", headers=HEADERS, json={"status":"DENIED"}).status_code == 200
    assert client.get("/api/v1/dashboard/overview", headers=HEADERS).json()["pending_approvals"] == 0
    assert client.get("/api/v1/approvals?status=PENDING", headers=HEADERS).json() == []
    assert repository.get_event(event["evaluation_id"])["decision"] == "REQUIRE_APPROVAL"


def test_approval_resolution_works_for_paginated_old_pending_item(policy_store, repository):
    client = client_for(policy_store, repository, ("viewer", "approver"))
    oldest = None
    for index in range(205):
        approval_id = repository.create_approval(str(uuid4()), f"2026-01-01T00:00:{index % 60:02d}+00:00")
        if oldest is None:
            oldest = approval_id
    response = client.post(f"/api/v1/approvals/{oldest}/resolution", headers=HEADERS, json={"status":"APPROVED"})
    assert response.status_code == 200
    assert response.json()["approval_id"] == oldest
    assert response.json()["status"] == "APPROVED"
