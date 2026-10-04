"""Safe, counts-only schema for the latest local pytest run."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Count = Annotated[int, Field(ge=0, strict=True)]
Duration = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class TestRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: Count
    failed: Count
    skipped: Count
    total: Count
    duration_seconds: Duration
    completed_at: datetime
    status: Literal["passed", "failed", "incomplete"]

    @model_validator(mode="after")
    def consistent(self):
        if self.total != self.passed + self.failed + self.skipped:
            raise ValueError("Inconsistent test counts")
        if self.completed_at.utcoffset() is None:
            raise ValueError("Test completion time must include a timezone")
        if self.failed and self.status != "failed":
            raise ValueError("Failed tests require failed status")
        if not self.failed and self.status == "failed":
            raise ValueError("Failed status requires failed tests")
        if self.status == "passed" and self.total == 0:
            raise ValueError("An empty run cannot pass")
        return self
