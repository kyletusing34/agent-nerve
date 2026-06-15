from __future__ import annotations

import re
from pathlib import Path

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[redacted-openai-key]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}\b", re.IGNORECASE), "Bearer [redacted-token]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted-aws-access-key]"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[redacted-private-key]",
    ),
]

_HOME_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/Users/[^/\s]+"), "/Users/[user]"),
    (re.compile(r"/home/[^/\s]+"), "/home/[user]"),
    (re.compile(r"C:\\Users\\[^\\\s]+"), r"C:\\Users\\[user]"),
]


def redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    for pattern, replacement in _HOME_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_json_like(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_json_like(item) for item in value]
    if isinstance(value, dict):
        return {str(key): redact_json_like(item) for key, item in value.items()}
    if isinstance(value, Path):
        return redact_text(str(value))
    return value
