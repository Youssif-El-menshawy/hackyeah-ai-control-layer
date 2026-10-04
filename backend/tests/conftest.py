from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from control_layer.api.auth import APIKeyAuthenticator, Principal
from control_layer.policy.loader import PolicyStore
from control_layer.storage.sqlite import SQLiteRepository


WORKSPACE = Path(__file__).resolve().parents[2]


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

