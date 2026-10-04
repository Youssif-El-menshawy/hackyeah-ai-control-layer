from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import jsonschema
import yaml


class PolicyValidationError(ValueError):
    pass


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class PolicySnapshot:
    data: Mapping[str, Any]
    version: str
    loaded_at: datetime

    @property
    def policy_id(self) -> str:
        return str(self.data["policy_id"])


class PolicyStore:
    """Loads validated YAML and atomically exposes the last good immutable snapshot."""

    def __init__(self, policy_path: Path, schema_path: Path) -> None:
        self.policy_path = policy_path
        self.schema_path = schema_path
        self._lock = threading.RLock()
        self._active = self._load()

    def _load(self) -> PolicySnapshot:
        try:
            schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
            raw = yaml.safe_load(self.policy_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.validate(raw, schema)
        except (json.JSONDecodeError, yaml.YAMLError, jsonschema.exceptions.SchemaError) as exc:
            raise PolicyValidationError(f"Policy document could not be parsed: {exc}") from exc
        except jsonschema.exceptions.ValidationError as exc:
            location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
            raise PolicyValidationError(f"{location}: {exc.message}") from exc
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        version = hashlib.sha256(canonical.encode()).hexdigest()
        return PolicySnapshot(_freeze(deepcopy(raw)), version, datetime.now(UTC))

    def get(self) -> PolicySnapshot:
        with self._lock:
            return self._active

    def reload(self) -> tuple[PolicySnapshot, bool]:
        candidate = self._load()
        with self._lock:
            changed = candidate.version != self._active.version
            if changed:
                self._active = candidate
            return self._active, changed
