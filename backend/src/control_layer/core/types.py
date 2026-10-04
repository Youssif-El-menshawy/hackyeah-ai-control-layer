from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Decision(StrEnum):
    ALLOW = "ALLOW"
    REDACT = "REDACT"
    BLOCK = "BLOCK"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class InputType(StrEnum):
    PROMPT = "prompt"
    TOOL_CALL = "tool_call"


class FailureKind(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    MALFORMED_OUTPUT = "malformed_output"
    OUTAGE = "outage"


@dataclass(frozen=True)
class Redaction:
    kind: str
    count: int


@dataclass(frozen=True)
class SanitizedContent:
    """A type boundary preventing adapters from accepting an untrusted raw string."""

    value: str
    redactions: tuple[Redaction, ...] = ()


@dataclass(frozen=True)
class RiskSignals:
    prompt_injection: float = 0.0
    data_exfiltration: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "prompt_injection": self.prompt_injection,
            "data_exfiltration": self.data_exfiltration,
        }


@dataclass(frozen=True)
class SemanticResult:
    signals: RiskSignals = field(default_factory=RiskSignals)
    failure: FailureKind | None = None


@dataclass(frozen=True)
class DecisionResult:
    decision: Decision
    reason_codes: tuple[str, ...]
    matched_rule_ids: tuple[str, ...]


JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject = dict[str, Any]

