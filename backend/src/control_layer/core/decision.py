from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .types import Decision, DecisionResult, FailureKind, InputType, SemanticResult


_PRECEDENCE = {
    Decision.ALLOW: 0,
    Decision.REDACT: 1,
    Decision.REQUIRE_APPROVAL: 2,
    Decision.BLOCK: 3,
}


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    return {
        "eq": lambda: actual == expected,
        "neq": lambda: actual != expected,
        "gte": lambda: actual >= expected,
        "gt": lambda: actual > expected,
        "lte": lambda: actual <= expected,
        "lt": lambda: actual < expected,
    }[operator]()


class DecisionEngine:
    def decide(
        self,
        policy: Mapping[str, Any],
        facts: Mapping[str, Any],
        semantic: SemanticResult,
        input_type: InputType,
    ) -> DecisionResult:
        merged = dict(facts)
        merged.update({f"semantic.{key}": value for key, value in semantic.signals.as_dict().items()})
        merged["semantic.available"] = semantic.failure is None

        matches: list[tuple[int, Decision, str, str]] = []
        for rule in policy["decision_rules"]:
            condition = rule["when"]
            mode = "all" if "all" in condition else "any"
            outcomes = (
                _compare(merged.get(item["fact"]), item["operator"], item["value"])
                for item in condition[mode]
            )
            if (all(outcomes) if mode == "all" else any(outcomes)):
                matches.append((int(rule["priority"]), Decision(rule["action"]), rule["reason_code"], rule["id"]))

        if semantic.failure is not None:
            failure_policy = policy["semantic"]["failure_policy"]
            action = (
                Decision(failure_policy["privileged_action"])
                if input_type is InputType.TOOL_CALL
                else Decision(failure_policy["prompt_actions"][semantic.failure.value])
            )
            matches.append((950, action, f"SEMANTIC_{semantic.failure.value.upper()}", "semantic-provider-failure"))

        if not matches:
            return DecisionResult(Decision.BLOCK, ("NO_POLICY_RULE_MATCHED",), ())

        top_priority = max(item[0] for item in matches)
        top = [item for item in matches if item[0] == top_priority]
        winning_action = max((item[1] for item in top), key=_PRECEDENCE.__getitem__)
        winners = sorted((item for item in top if item[1] is winning_action), key=lambda item: item[3])
        return DecisionResult(
            winning_action,
            tuple(sorted({item[2] for item in winners})),
            tuple(item[3] for item in winners),
        )

