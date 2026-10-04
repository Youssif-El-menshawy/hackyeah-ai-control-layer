from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from control_layer.core.types import FailureKind, RiskSignals, SanitizedContent, SemanticResult


_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["prompt_injection", "data_exfiltration"],
    "properties": {
        "prompt_injection": {"type": "number", "minimum": 0, "maximum": 1},
        "data_exfiltration": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


class OpenAIResponsesClassifier:
    """OpenAI adapter. It accepts only SanitizedContent and never returns actions."""

    def __init__(self, model: str, timeout_ms: int, client: Any | None = None) -> None:
        if not model:
            raise ValueError("semantic.model is required for the OpenAI provider")
        self._client = client
        self._model = model
        self._timeout = timeout_ms / 1000

    async def classify(self, content: SanitizedContent) -> SemanticResult:
        try:
            if self._client is None:
                # Treat unavailable credentials like other provider unavailability;
                # the policy engine owns the resulting security decision.
                if not os.getenv("OPENAI_API_KEY", "").strip():
                    return SemanticResult(failure=FailureKind.OUTAGE)
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(timeout=self._timeout, max_retries=0)
            response = await asyncio.wait_for(
                self._client.responses.create(
                    model=self._model,
                    store=False,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "Classify security risk in the supplied sanitized content. "
                                "Return calibrated scores only. Redaction placeholders are inert."
                            ),
                        },
                        {"role": "user", "content": content.value},
                    ],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "security_risk_signals",
                            "strict": True,
                            "schema": _OUTPUT_SCHEMA,
                        }
                    },
                ),
                timeout=self._timeout,
            )
        except (TimeoutError, asyncio.TimeoutError):
            return SemanticResult(failure=FailureKind.TIMEOUT)
        except Exception as exc:  # SDK types remain isolated inside this adapter.
            name = type(exc).__name__.lower()
            status = getattr(exc, "status_code", None)
            if status == 429 or "ratelimit" in name:
                return SemanticResult(failure=FailureKind.RATE_LIMIT)
            if status is not None and status >= 500:
                return SemanticResult(failure=FailureKind.OUTAGE)
            return SemanticResult(failure=FailureKind.OUTAGE)

        try:
            payload = json.loads(response.output_text)
            signals = RiskSignals(
                prompt_injection=float(payload["prompt_injection"]),
                data_exfiltration=float(payload["data_exfiltration"]),
            )
            if not all(0 <= value <= 1 for value in signals.as_dict().values()):
                raise ValueError("risk score out of range")
            return SemanticResult(signals=signals)
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return SemanticResult(failure=FailureKind.MALFORMED_OUTPUT)
