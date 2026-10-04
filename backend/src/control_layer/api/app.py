from __future__ import annotations

import os
import base64
import json
from typing import Literal
from uuid import UUID
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from control_layer.benchmark import BenchmarkReport
from control_layer.core.service import EvaluationService
from control_layer.policy.loader import PolicyStore, PolicyValidationError
from control_layer.storage.sqlite import SQLiteRepository

from .auth import APIKeyAuthenticator, Principal, require_scope
from .dashboard import live_overview, policy_overview
from .test_results import TestRunSummary
from .schemas import (
    Approval,
    ApprovalResolution,
    BudgetUsage,
    EvaluationRequest,
    EvaluationResponse,
    EventPage,
    PolicyMetadata,
    PolicyReloadResponse,
)


def _root() -> Path:
    return Path(__file__).resolve().parents[4]


def create_app(
    *,
    policy_store: PolicyStore | None = None,
    repository: SQLiteRepository | None = None,
    authenticator: APIKeyAuthenticator | None = None,
    service: EvaluationService | None = None,
) -> FastAPI:
    root = _root()
    policies = policy_store or PolicyStore(
        Path(os.getenv("CONTROL_LAYER_POLICY_PATH", root / "policies/example.policy.yaml")),
        Path(os.getenv("CONTROL_LAYER_POLICY_SCHEMA_PATH", root / "policies/policy.schema.json")),
    )
    repo = repository or SQLiteRepository(Path(os.getenv("CONTROL_LAYER_DB_PATH", root / "backend/control-layer.sqlite3")))
    evaluator = service or EvaluationService(policies, repo)

    app = FastAPI(title="HackYeah AI Control Layer", version="0.1.0")
    app.state.policies = policies
    app.state.repository = repo
    app.state.service = evaluator
    app.state.authenticator = authenticator or APIKeyAuthenticator()
    benchmark_path = Path(os.getenv("CONTROL_LAYER_BENCHMARK_PATH", root / "backend/benchmark-results/latest.json"))
    test_results_path = Path(os.getenv("CONTROL_LAYER_TEST_RESULTS_PATH", root / "backend/latest_test_results.json"))

    @app.exception_handler(HTTPException)
    async def http_problem(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": str(exc.detail),
                "status": exc.status_code,
            },
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_problem(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Request validation failed",
                "status": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "detail": str(exc),
            },
        )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/tests/latest", response_model=TestRunSummary | None)
    def latest_tests(response: Response, _: Principal = Depends(require_scope("viewer"))) -> TestRunSummary | None:
        response.headers["Cache-Control"] = "no-store"
        try:
            # Counts-only artifact from pytest. Reject extra fields and oversized input.
            with test_results_path.open("rb") as stream:
                payload = stream.read(4097)
            if len(payload) > 4096:
                raise ValueError("oversized")
            return TestRunSummary.model_validate_json(payload)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, ValidationError):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Test result summary is invalid or unreadable") from None

    @app.get("/api/v1/benchmarks/latest", response_model=BenchmarkReport | None)
    def latest_benchmark(response: Response, _: Principal = Depends(require_scope("viewer"))) -> BenchmarkReport | None:
        response.headers["Cache-Control"] = "no-store"
        try:
            # A fixed server-side path, not a user-selected file or an execution endpoint.
            return BenchmarkReport.model_validate_json(benchmark_path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValueError, ValidationError):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Benchmark report is invalid or unreadable") from None

    @app.post("/api/v1/evaluations", response_model=EvaluationResponse)
    async def evaluate(
        body: EvaluationRequest,
        _: Principal = Depends(require_scope("evaluate")),
    ) -> EvaluationResponse:
        try:
            return await app.state.service.evaluate(body)
        except ValueError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    @app.get("/api/v1/events", response_model=EventPage)
    async def events(
        limit: int = Query(50, ge=1, le=200),
        decision: str | None = None,
        agent_id: str | None = Query(None, max_length=128),
        input_type: Literal["prompt", "tool_call"] | None = None,
        search: str | None = Query(None, max_length=200),
        cursor: str | None = Query(None, max_length=512),
        _: Principal = Depends(require_scope("viewer")),
    ) -> EventPage:
        before = None
        if cursor:
            try:
                before = json.loads(base64.urlsafe_b64decode(cursor).decode())
                if not isinstance(before, list) or len(before) != 2 or not all(isinstance(value, str) for value in before):
                    raise ValueError
                datetime.fromisoformat(before[0])
                UUID(before[1])
            except (ValueError, TypeError, UnicodeError):
                raise HTTPException(400, "Invalid event cursor") from None
        items, more = repo.event_page(limit, decision=decision, agent_id=agent_id, input_type=input_type, search=search, before=before)
        next_cursor = base64.urlsafe_b64encode(json.dumps([items[-1]["created_at"], items[-1]["evaluation_id"]]).encode()).decode() if more else None
        return EventPage(items=items, next_cursor=next_cursor)

    @app.get("/api/v1/events/{evaluation_id}")
    async def event_detail(evaluation_id: UUID, _: Principal = Depends(require_scope("viewer"))):
        event = repo.get_event(str(evaluation_id))
        if event is None:
            raise HTTPException(404, "Event not found")
        return event

    @app.get("/api/v1/dashboard/overview")
    async def dashboard_overview(principal: Principal = Depends(require_scope("viewer"))):
        return live_overview(repo, policies.get(), principal)

    @app.get("/api/v1/policies/overview")
    async def active_policy_overview(_: Principal = Depends(require_scope("viewer"))):
        return policy_overview(policies.get())

    @app.get("/api/v1/budgets", response_model=list[BudgetUsage])
    async def budgets(_: Principal = Depends(require_scope("viewer"))) -> list[BudgetUsage]:
        snapshot = policies.get()
        config = snapshot.data["budgets"]
        usages = repo.current_budget_usage(int(config["window_seconds"]))
        result = []
        for usage in usages:
            limits = config.get("per_agent", {}).get(usage["agent_id"], config["defaults"])
            result.append(BudgetUsage(**usage, max_requests=limits["max_requests"], max_input_tokens=limits["max_input_tokens"]))
        return result

    def metadata() -> PolicyMetadata:
        snapshot = policies.get()
        return PolicyMetadata(
            policy_id=snapshot.policy_id,
            schema_version=str(snapshot.data["schema_version"]),
            policy_version=snapshot.version,
            loaded_at=snapshot.loaded_at,
        )

    @app.get("/api/v1/policies/active", response_model=PolicyMetadata)
    async def active_policy(_: Principal = Depends(require_scope("viewer"))) -> PolicyMetadata:
        return metadata()

    @app.post("/api/v1/policies/reload", response_model=PolicyReloadResponse)
    async def reload_policy(_: Principal = Depends(require_scope("admin"))) -> PolicyReloadResponse:
        try:
            _, changed = policies.reload()
        except PolicyValidationError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        return PolicyReloadResponse(changed=changed, active=metadata())

    @app.get("/api/v1/approvals", response_model=list[Approval])
    async def approvals(
        limit: int = Query(50, ge=1, le=200),
        status_filter: Literal["PENDING", "APPROVED", "DENIED"] | None = Query(None, alias="status"),
        offset: int = Query(0, ge=0),
        _: Principal = Depends(require_scope("approver")),
    ) -> list[Approval]:
        return [Approval.model_validate(item) for item in repo.list_approvals(limit, status_filter, offset)]

    @app.post("/api/v1/approvals/{approval_id}/resolution", response_model=Approval)
    async def resolve_approval(
        approval_id: str,
        body: ApprovalResolution,
        principal: Principal = Depends(require_scope("approver")),
    ) -> Approval:
        updated = repo.resolve_approval(
            approval_id, body.status, principal.name, body.reason, datetime.now(UTC).isoformat()
        )
        if not updated:
            raise HTTPException(status.HTTP_409_CONFLICT, "Approval is missing or already resolved")
        item = repo.get_approval(approval_id)
        return Approval.model_validate(item)

    return app
