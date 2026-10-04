from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class SQLiteRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS events (
              evaluation_id TEXT PRIMARY KEY,
              request_id TEXT NOT NULL UNIQUE,
              agent_id TEXT NOT NULL,
              model TEXT NOT NULL,
              input_type TEXT NOT NULL,
              tool_name TEXT,
              decision TEXT NOT NULL,
              reason_codes TEXT NOT NULL,
              policy_version TEXT NOT NULL,
              input_sha256 TEXT NOT NULL,
              redactions TEXT NOT NULL,
              risk_signals TEXT NOT NULL,
              semantic_failure TEXT,
              estimated_input_tokens INTEGER NOT NULL,
              latency_ms INTEGER NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
            CREATE TABLE IF NOT EXISTS budget_usage (
              agent_id TEXT NOT NULL,
              window_start INTEGER NOT NULL,
              requests INTEGER NOT NULL,
              input_tokens INTEGER NOT NULL,
              PRIMARY KEY (agent_id, window_start)
            );
            CREATE TABLE IF NOT EXISTS approvals (
              approval_id TEXT PRIMARY KEY,
              evaluation_id TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','DENIED')),
              resolved_by TEXT,
              resolution_reason TEXT,
              resolved_at TEXT,
              created_at TEXT NOT NULL
            );
            """
        )

    def reserve_budget(self, agent_id: str, tokens: int, window_seconds: int, limits: dict[str, int]) -> bool:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            try:
                row = cursor.execute(
                    "SELECT requests, input_tokens FROM budget_usage WHERE agent_id=? AND window_start=?",
                    (agent_id, window_start),
                ).fetchone()
                requests = (row["requests"] if row else 0) + 1
                input_tokens = (row["input_tokens"] if row else 0) + tokens
                if requests > limits["max_requests"] or input_tokens > limits["max_input_tokens"]:
                    cursor.execute("ROLLBACK")
                    return False
                cursor.execute(
                    """INSERT INTO budget_usage(agent_id, window_start, requests, input_tokens)
                       VALUES(?,?,?,?) ON CONFLICT(agent_id, window_start) DO UPDATE SET
                       requests=excluded.requests, input_tokens=excluded.input_tokens""",
                    (agent_id, window_start, requests, input_tokens),
                )
                cursor.execute("COMMIT")
                return True
            except Exception:
                cursor.execute("ROLLBACK")
                raise

    def append_event(self, event: dict[str, Any]) -> None:
        columns = tuple(event)
        values = [json.dumps(event[key]) if isinstance(event[key], (list, dict)) else event[key] for key in columns]
        placeholders = ",".join("?" for _ in columns)
        self._connection.execute(
            f"INSERT INTO events ({','.join(columns)}) VALUES ({placeholders})", values  # noqa: S608
        )

    def get_event_by_request(self, request_id: str) -> dict[str, Any] | None:
        row = self._connection.execute("SELECT * FROM events WHERE request_id=?", (request_id,)).fetchone()
        return self._decode_event(row) if row else None

    def list_events(self, limit: int = 50, decision: str | None = None) -> list[dict[str, Any]]:
        if decision:
            rows = self._connection.execute(
                "SELECT * FROM events WHERE decision=? ORDER BY created_at DESC LIMIT ?", (decision, limit)
            ).fetchall()
        else:
            rows = self._connection.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode_event(row) for row in rows]

    def current_budget_usage(self, window_seconds: int) -> list[dict[str, int | str]]:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        rows = self._connection.execute(
            "SELECT agent_id, window_start, requests, input_tokens FROM budget_usage WHERE window_start=? ORDER BY agent_id",
            (window_start,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _decode_event(row: sqlite3.Row) -> dict[str, Any]:
        event = dict(row)
        for key in ("reason_codes", "redactions", "risk_signals"):
            event[key] = json.loads(event[key])
        return event

    def create_approval(self, evaluation_id: str, created_at: str) -> str:
        approval_id = str(uuid.uuid4())
        self._connection.execute(
            "INSERT INTO approvals(approval_id,evaluation_id,status,created_at) VALUES(?,?,'PENDING',?)",
            (approval_id, evaluation_id, created_at),
        )
        return approval_id

    def list_approvals(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._connection.execute("SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def approval_for_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM approvals WHERE evaluation_id=?", (evaluation_id,)
        ).fetchone()
        return dict(row) if row else None

    def resolve_approval(self, approval_id: str, status: str, actor: str, reason: str | None, at: str) -> bool:
        cursor = self._connection.execute(
            """UPDATE approvals SET status=?, resolved_by=?, resolution_reason=?, resolved_at=?
               WHERE approval_id=? AND status='PENDING'""",
            (status, actor, reason, at, approval_id),
        )
        return cursor.rowcount == 1
