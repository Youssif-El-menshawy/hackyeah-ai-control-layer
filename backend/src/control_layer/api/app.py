from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from control_layer.core.service import EvaluationService
from control_layer.policy.loader import PolicyStore, PolicyValidationError
from control_layer.storage.sqlite import SQLiteRepository

from .auth import APIKeyAuthenticator, Principal, require_scope
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
        _: Principal = Depends(require_scope("viewer")),
    ) -> EventPage:
        return EventPage(items=repo.list_events(limit, decision))

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
        _: Principal = Depends(require_scope("approver")),
    ) -> list[Approval]:
        return [Approval.model_validate(item) for item in repo.list_approvals(limit)]

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
        item = next(item for item in repo.list_approvals(200) if item["approval_id"] == approval_id)
        return Approval.model_validate(item)

    return app
