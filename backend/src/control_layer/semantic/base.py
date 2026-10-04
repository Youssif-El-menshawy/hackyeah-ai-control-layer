from __future__ import annotations

from typing import Protocol

from control_layer.core.types import SanitizedContent, SemanticResult


class SemanticClassifier(Protocol):
    async def classify(self, content: SanitizedContent) -> SemanticResult: ...

