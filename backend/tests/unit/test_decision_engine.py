from control_layer.core.decision import DecisionEngine
from control_layer.core.types import Decision, FailureKind, InputType, RiskSignals, SemanticResult


def _facts(**updates):
    values = {
        "model.allowed": True,
        "tool.allowed": True,
        "budget.allowed": True,
        "detector.email": False,
        "detector.phone": False,
        "detector.api_key": False,
        "detector.secret": False,
    }
    values.update(updates)
    return values


def test_llm_signal_is_mapped_by_policy_not_used_as_a_decision(policy_store):
    result = DecisionEngine().decide(
        policy_store.get().data,
        _facts(),
        SemanticResult(RiskSignals(prompt_injection=0.7)),
        InputType.PROMPT,
    )
    assert result.decision is Decision.REQUIRE_APPROVAL
    assert result.reason_codes == ("PROMPT_INJECTION_REVIEW",)


def test_tool_call_fails_closed_on_semantic_timeout(policy_store):
    result = DecisionEngine().decide(
        policy_store.get().data,
        _facts(),
        SemanticResult(failure=FailureKind.TIMEOUT),
        InputType.TOOL_CALL,
    )
    assert result.decision is Decision.BLOCK
    assert result.reason_codes == ("SEMANTIC_TIMEOUT",)


def test_prompt_uses_configured_semantic_failure_fallback(policy_store):
    result = DecisionEngine().decide(
        policy_store.get().data,
        _facts(),
        SemanticResult(failure=FailureKind.RATE_LIMIT),
        InputType.PROMPT,
    )
    assert result.decision is Decision.REQUIRE_APPROVAL


def test_deterministic_block_outranks_provider_failure(policy_store):
    result = DecisionEngine().decide(
        policy_store.get().data,
        _facts(**{"model.allowed": False}),
        SemanticResult(failure=FailureKind.OUTAGE),
        InputType.PROMPT,
    )
    assert result.decision is Decision.BLOCK
    assert result.reason_codes == ("DETERMINISTIC_CONTROL_FAILED",)

