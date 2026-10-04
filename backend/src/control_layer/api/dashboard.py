"""Read-only projections; no inference of historical policy facts."""
from collections import Counter


def policy_overview(snapshot):
    policy = snapshot.data
    semantic = policy["semantic"]
    thresholds = []
    for rule in policy["decision_rules"]:
        for mode, conditions in rule["when"].items():
            for condition in conditions:
                if condition["fact"] in ("semantic.prompt_injection", "semantic.data_exfiltration"):
                    thresholds.append({**dict(condition), "rule_id": rule["id"], "action": rule["action"],
                                       "priority": rule["priority"], "compound": len(conditions) > 1, "mode": mode})
    return {
        "policy_id": snapshot.policy_id, "schema_version": policy["schema_version"], "policy_version": snapshot.version, "loaded_at": snapshot.loaded_at,
        "semantic_provider": semantic["provider"], "semantic_model": semantic.get("model"),
        "allowed_models": list(policy["models"]["allowed"]), "thresholds": thresholds,
        "enabled_detectors": [name for name, config in policy["sanitization"]["detectors"].items() if config["enabled"]],
        "agents": {name: {"allowed_tools": list(config["allowed_tools"]), "denied_tools": list(config.get("denied_tools", ()))}
                   for name, config in policy["agents"].items()},
        "budget_window_seconds": policy["budgets"]["window_seconds"],
        "budget_defaults": dict(policy["budgets"]["defaults"]),
        "budget_per_agent": {name: dict(value) for name, value in policy["budgets"].get("per_agent", {}).items()},
        "failure_policy": {"privileged_action": semantic["failure_policy"]["privileged_action"],
                           "prompt_actions": dict(semantic["failure_policy"]["prompt_actions"])},
    }


def live_overview(repo, snapshot, principal):
    events = repo.list_events(100)
    counts = Counter(item["decision"] for item in events)
    latest = next((item for item in events if item["policy_version"] == snapshot.version), None)
    return {
        "policy_version": snapshot.version, "sample_size": len(events), "sample_limit": 100,
        "counts": {decision: counts[decision] for decision in ("ALLOW", "REDACT", "BLOCK", "REQUIRE_APPROVAL")},
        "average_latency_ms": sum(item["latency_ms"] for item in events) / len(events) if events else None,
        "pending_approvals": repo.pending_approval_count(),
        "agents": sorted({item["agent_id"] for item in events}),
        "activity": {
            "prompt_injection": sum("PROMPT_INJECTION_REVIEW" in item["reason_codes"] for item in events),
            "data_exfiltration": sum("DATA_EXFILTRATION_HIGH_RISK" in item["reason_codes"] for item in events),
            "sensitive_data": sum(bool(item["redactions"]) for item in events),
            "provider_failures": sum(item["semantic_failure"] is not None for item in events),
            "deterministic_blocks": sum("DETERMINISTIC_CONTROL_FAILED" in item["reason_codes"] for item in events),
            "unauthorized_tools": None, "budget_violations": None,
        },
        "latest_semantic": {"failure": latest["semantic_failure"], "created_at": latest["created_at"]} if latest else None,
        "can_approve": bool({"approver", "admin"} & principal.scopes),
        "can_reload": "admin" in principal.scopes,
    }
