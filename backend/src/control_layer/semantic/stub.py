from __future__ import annotations

from dataclasses import dataclass

from control_layer.core.types import RiskSignals, SanitizedContent, SemanticResult


@dataclass
class StubSemanticClassifier:
    """Offline deterministic classifier for local development and tests."""

    prompt_injection_score: float = 0.0
    data_exfiltration_score: float = 0.0

    async def classify(self, content: SanitizedContent) -> SemanticResult:
        del content
        return SemanticResult(RiskSignals(self.prompt_injection_score, self.data_exfiltration_score))

