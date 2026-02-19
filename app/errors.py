from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApiError(Exception):
    code: str
    message: str
    status_code: int = 400
    retryable: bool = False
    hint: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "hint": self.hint,
            }
        }
