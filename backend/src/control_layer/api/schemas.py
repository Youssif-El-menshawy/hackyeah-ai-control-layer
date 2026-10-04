from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from control_layer.core.types import Decision, InputType


class PromptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[InputType.PROMPT] = InputType.PROMPT
    content: str = Field(min_length=1, max_length=100_000)


class ToolCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal[InputType.TOOL_CALL] = InputType.TOOL_CALL
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, object]


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    agent_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    metadata: dict[str, str] = Field(default_factory=dict)
    input: Annotated[PromptInput | ToolCallInput, Field(discriminator="type")]


class RedactionSummary(BaseModel):
    kind: Literal["email", "phone", "api_key", "secret"]
    count: int = Field(ge=1)


class RiskSignal(BaseModel):
    label: Literal["prompt_injection", "data_exfiltration"]
    score: float = Field(ge=0, le=1)


class EvaluationResponse(BaseModel):
    evaluation_id: UUID
    request_id: UUID
    decision: Decision
    reason_codes: list[str]
    policy_version: str
    sanitized_content: str | None = None
    redactions: list[RedactionSummary]
    risk_signals: list[RiskSignal]
    approval_id: UUID | None = None
    created_at: datetime


class PolicyMetadata(BaseModel):
    policy_id: str
    schema_version: str
    policy_version: str
    loaded_at: datetime


class PolicyReloadResponse(BaseModel):
    changed: bool
    active: PolicyMetadata


class EventPage(BaseModel):
    items: list[dict[str, object]]
    next_cursor: str | None = None


class ApprovalResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["APPROVED", "DENIED"]
    reason: str | None = Field(default=None, max_length=500)


class Approval(BaseModel):
    approval_id: UUID
    evaluation_id: UUID
    status: Literal["PENDING", "APPROVED", "DENIED"]
    resolved_by: str | None = None
    resolution_reason: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime


class BudgetUsage(BaseModel):
    agent_id: str
    window_start: int
    requests: int
    input_tokens: int
    max_requests: int
    max_input_tokens: int
