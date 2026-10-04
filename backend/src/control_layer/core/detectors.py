from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from .types import Redaction, SanitizedContent


@dataclass(frozen=True)
class _Finding:
    start: int
    end: int
    kind: str
    priority: int


class DeterministicSanitizer:
    """Regex-based sanitizer with deterministic overlap and placeholder behavior."""

    _BUILT_INS: dict[str, tuple[int, tuple[str, ...]]] = {
        "secret": (
            40,
            (
                r"(?i)\b(?:password|passwd|secret|client_secret)\s*[:=]\s*['\"]?[^\s,'\";]{6,}",
                r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            ),
        ),
        "api_key": (
            30,
            (
                r"\bsk-[A-Za-z0-9_-]{16,}\b",
                r"\bAKIA[0-9A-Z]{16}\b",
                r"(?i)\b(?:api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{12,}",
            ),
        ),
        "email": (
            20,
            (
                # Dot-separated local parts and DNS labels; punctuation is not consumed.
                r"(?<![\w.%+@-])[A-Z0-9_%+-]+(?:\.[A-Z0-9_%+-]+)*@"
                r"(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}"
                # Allow sentence-ending periods, but not a partial domain match.
                r"(?![\w%+@-]|\.+[\w%+@-])",
            ),
        ),
        "phone": (10, (r"(?<!\w)(?:\+?\d[\d .()\-]{7,}\d)(?!\w)",)),
    }

    def __init__(self, detector_config: Mapping[str, object]) -> None:
        patterns: dict[str, tuple[int, tuple[re.Pattern[str], ...]]] = {}
        for kind, (priority, built_ins) in self._BUILT_INS.items():
            config = detector_config.get(kind, {})
            if not isinstance(config, Mapping) or not config.get("enabled", False):
                continue
            extras = config.get("patterns", [])
            source_patterns = (*built_ins, *(extras if isinstance(extras, list) else []))
            flags = re.IGNORECASE if kind == "email" else 0
            patterns[kind] = (priority, tuple(re.compile(item, flags) for item in source_patterns))
        self._patterns = patterns

    def sanitize(self, content: str) -> SanitizedContent:
        candidates: list[_Finding] = []
        for kind, (priority, patterns) in self._patterns.items():
            for pattern in patterns:
                candidates.extend(_Finding(m.start(), m.end(), kind, priority) for m in pattern.finditer(content))

        # Earlier positions win; at the same position prefer higher-priority and longer matches.
        candidates.sort(key=lambda f: (f.start, -f.priority, -(f.end - f.start), f.kind))
        accepted: list[_Finding] = []
        for finding in candidates:
            if any(finding.start < prior.end and finding.end > prior.start for prior in accepted):
                continue
            accepted.append(finding)
        accepted.sort(key=lambda f: f.start)

        counts: Counter[str] = Counter()
        parts: list[str] = []
        cursor = 0
        for finding in accepted:
            counts[finding.kind] += 1
            parts.append(content[cursor:finding.start])
            parts.append(f"[REDACTED_{finding.kind.upper()}_{counts[finding.kind]}]")
            cursor = finding.end
        parts.append(content[cursor:])
        summary = tuple(Redaction(kind, counts[kind]) for kind in sorted(counts))
        return SanitizedContent("".join(parts), summary)
