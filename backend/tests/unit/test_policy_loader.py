from __future__ import annotations

import pytest
import yaml

from control_layer.policy.loader import PolicyValidationError


def test_policy_loads_as_immutable_versioned_snapshot(policy_store):
    snapshot = policy_store.get()
    assert snapshot.policy_id == "hackyeah-default"
    assert len(snapshot.version) == 64
    with pytest.raises(TypeError):
        snapshot.data["policy_id"] = "changed"


def test_invalid_reload_keeps_last_good_snapshot(policy_store):
    original = policy_store.get()
    policy_store.policy_path.write_text("schema_version: '1.0'\n", encoding="utf-8")
    with pytest.raises(PolicyValidationError):
        policy_store.reload()
    assert policy_store.get() is original


def test_openai_provider_requires_configuration_owned_model(policy_store):
    policy = yaml.safe_load(policy_store.policy_path.read_text(encoding="utf-8"))
    policy["semantic"]["provider"] = "openai"
    policy["semantic"].pop("model", None)
    policy_store.policy_path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(PolicyValidationError, match="model"):
        policy_store.reload()
