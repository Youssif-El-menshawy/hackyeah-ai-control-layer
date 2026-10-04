from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


@dataclass(frozen=True)
class Principal:
    name: str
    scopes: frozenset[str]


class APIKeyAuthenticator:
    def __init__(self, entries: dict[str, Principal] | None = None) -> None:
        self._entries = entries if entries is not None else self._from_environment()

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def _from_environment(self) -> dict[str, Principal]:
        raw = os.getenv("CONTROL_LAYER_API_KEYS", "{}")
        parsed = json.loads(raw)
        return {
            self._digest(key): Principal(config["name"], frozenset(config["scopes"]))
            for key, config in parsed.items()
        }

    def authenticate(self, key: str) -> Principal | None:
        digest = self._digest(key)
        for stored, principal in self._entries.items():
            if hmac.compare_digest(digest, stored):
                return principal
        return None


_bearer = HTTPBearer(auto_error=False)


def require_scope(scope: str):
    async def dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> Principal:
        if credentials is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer API key")
        principal = request.app.state.authenticator.authenticate(credentials.credentials)
        if principal is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer API key")
        if scope not in principal.scopes and "admin" not in principal.scopes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing {scope} scope")
        return principal

    return dependency

