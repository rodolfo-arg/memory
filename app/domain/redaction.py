from __future__ import annotations

import re

REDACTION_PATTERNS = [
    re.compile(r"\b(sk-[A-Za-z0-9]{20,})\b"),
    re.compile(r"\b(ghp_[A-Za-z0-9]{20,})\b"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?)\b", re.IGNORECASE),
]


def redact_text(text: str) -> str:
    redacted = text
    for pattern in REDACTION_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted
