from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from control_layer.api.schemas import EvaluationRequest, EvaluationResponse, RedactionSummary, RiskSignal
from control_layer.policy.loader import PolicySnapshot, PolicyStore
from control_layer.semantic.base import SemanticClassifier
from control_layer.semantic.openai_adapter import OpenAIResponsesClassifier
from control_layer.semantic.stub import StubSemanticClassifier
from control_layer.storage.sqlite import SQLiteRepository

from .decision import DecisionEngine
from .detectors import DeterministicSanitizer
from .types import Decision, InputType


class EvaluationService:
    def __init__(
        self,
        policies: PolicyStore,
        repository: SQLiteRepository,
        classifier: SemanticClassifier | None = None,
    ) -> None:
        self.policies = policies
        self.repository = repository
        self._injected_classifier = classifier
        self._classifiers: dict[str, SemanticClassifier] = {}
        self._engine = DecisionEngine()

    def _classifier(self, snapshot: PolicySnapshot) -> SemanticClassifier:
        if self._injected_classifier is not None:
            return self._injected_classifier
        if snapshot.version in self._classifiers:
            return self._classifiers[snapshot.version]
        config = snapshot.data["semantic"]
        provider = config["provider"]
        if provider == "stub":
            classifier: SemanticClassifier = StubSemanticClassifier()
        elif provider == "openai":
            classifier = OpenAIResponsesClassifier(str(config.get("model", "")), int(config["timeout_ms"]))
        else:
            raise ValueError(f"Unsupported semantic provider: {provider}")
        self._classifiers[snapshot.version] = classifier
        return classifier

    async def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        existing = self.repository.get_event_by_request(str(request.request_id))
        if existing is not None:
            approval = self.repository.approval_for_evaluation(existing["evaluation_id"])
            return EvaluationResponse(
                evaluation_id=existing["evaluation_id"],
                request_id=existing["request_id"],
                decision=existing["decision"],
                reason_codes=existing["reason_codes"],
                policy_version=existing["policy_version"],
                sanitized_content=None,
                redactions=existing["redactions"],
                risk_signals=existing["risk_signals"],
                approval_id=approval["approval_id"] if approval else None,
                created_at=existing["created_at"],
            )
        snapshot = self.policies.get()
        started = time.perf_counter()
        input_type = InputType(request.input.type)
        tool_name = getattr(request.input, "tool_name", None)
        raw = (
            request.input.content
            if input_type is InputType.PROMPT
            else json.dumps(request.input.arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        )
        sanitizer = DeterministicSanitizer(snapshot.data["sanitization"]["detectors"])
        sanitized = sanitizer.sanitize(raw)
        kinds = {item.kind for item in sanitized.redactions}

        models = set(snapshot.data["models"]["allowed"])
        agent = snapshot.data["agents"].get(request.agent_id)
        tool_allowed = input_type is InputType.PROMPT
        if input_type is InputType.TOOL_CALL and agent is not None:
            tool_allowed = tool_name in agent["allowed_tools"] and tool_name not in agent.get("denied_tools", ())

        tokens = request.estimated_input_tokens
        if tokens is None:
            tokens = max(1, (len(raw) + 3) // 4)
        budget_config = snapshot.data["budgets"]
        configured_limit = budget_config.get("per_agent", {}).get(request.agent_id, budget_config["defaults"])
        budget_allowed = self.repository.reserve_budget(
            request.agent_id,
            tokens,
            int(budget_config["window_seconds"]),
            {"max_requests": int(configured_limit["max_requests"]), "max_input_tokens": int(configured_limit["max_input_tokens"])},
        )
        facts: dict[str, Any] = {
            "model.allowed": request.model in models,
            "tool.allowed": tool_allowed and agent is not None,
            "budget.allowed": budget_allowed,
            **{f"detector.{kind}": kind in kinds for kind in ("email", "phone", "api_key", "secret")},
        }

        semantic = await self._classifier(snapshot).classify(sanitized)
        result = self._engine.decide(snapshot.data, facts, semantic, input_type)
        evaluation_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)
        risk_signals = [RiskSignal(label=key, score=value) for key, value in semantic.signals.as_dict().items()]
        redactions = [RedactionSummary(kind=item.kind, count=item.count) for item in sanitized.redactions]
        event = {
            "evaluation_id": evaluation_id,
            "request_id": str(request.request_id),
            "agent_id": request.agent_id,
            "model": request.model,
            "input_type": input_type.value,
            "tool_name": tool_name,
            "decision": result.decision.value,
            "reason_codes": list(result.reason_codes),
            "policy_version": snapshot.version,
            "input_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "redactions": [item.model_dump() for item in redactions],
            "risk_signals": [item.model_dump() for item in risk_signals],
            "semantic_failure": semantic.failure.value if semantic.failure else None,
            "estimated_input_tokens": tokens,
            "latency_ms": max(0, int((time.perf_counter() - started) * 1000)),
            "created_at": created_at.isoformat(),
        }
        self.repository.append_event(event)
        approval_id = None
        if result.decision is Decision.REQUIRE_APPROVAL:
            approval_id = self.repository.create_approval(evaluation_id, created_at.isoformat())
        return EvaluationResponse(
            evaluation_id=evaluation_id,
            request_id=request.request_id,
            decision=result.decision,
            reason_codes=list(result.reason_codes),
            policy_version=snapshot.version,
            sanitized_content=sanitized.value if result.decision in (Decision.ALLOW, Decision.REDACT) else None,
            redactions=redactions,
            risk_signals=risk_signals,
            approval_id=approval_id,
            created_at=created_at,
        )
