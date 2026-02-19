from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ParsedMessage:
    role: str
    content: str
    created_at: str
    source_ref: str = ""


_ALLOWED_ROLES = {"user", "assistant", "tool", "system"}


def parse_transcript_delta(transcript_path: str, last_line: int) -> tuple[list[ParsedMessage], int]:
    path = Path(transcript_path)
    if not path.exists():
        return [], last_line

    parsed: list[ParsedMessage] = []
    total_lines = last_line

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            total_lines = line_number
            if line_number <= last_line:
                continue

            raw = line.strip()
            if not raw:
                continue

            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue

            message = _extract_message(record, source_ref=f"line:{line_number}")
            if message is None:
                continue
            parsed.append(message)

    return parsed, total_lines


def _extract_message(record: dict[str, Any], *, source_ref: str = "") -> ParsedMessage | None:
    role = _extract_role(record)
    if role not in _ALLOWED_ROLES:
        return None

    content = _extract_content(record).strip()
    if not content:
        return None

    created_at = _extract_created_at(record)
    return ParsedMessage(role=role, content=content, created_at=created_at, source_ref=source_ref)


def _extract_role(record: dict[str, Any]) -> str:
    candidates = [
        record.get("role"),
        record.get("type"),
        _nested_get(record, "message", "role"),
        _nested_get(record, "payload", "role"),
    ]

    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        normalized = candidate.lower().strip()
        if normalized in _ALLOWED_ROLES:
            return normalized
        if normalized in {"user_message", "human"}:
            return "user"
        if normalized in {"assistant_message", "ai"}:
            return "assistant"
    return ""


def _extract_content(record: dict[str, Any]) -> str:
    sources: list[Any] = [
        record.get("content"),
        _nested_get(record, "message", "content"),
        _nested_get(record, "payload", "content"),
        record.get("text"),
        _nested_get(record, "message", "text"),
    ]

    for source in sources:
        content = _flatten_text(source).strip()
        if content:
            return content

    return _flatten_text(record)


def _extract_created_at(record: dict[str, Any]) -> str:
    for key in ("created_at", "timestamp", "time", "ts"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return _nested_get(record, "message", "created_at") or ""


def _nested_get(data: dict[str, Any], *path: str) -> Any:
    node: Any = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _flatten_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for item in node if (part := _flatten_text(item)))
    if isinstance(node, dict):
        preferred_keys = ("text", "content", "value", "output", "input", "message")
        for key in preferred_keys:
            if key in node:
                part = _flatten_text(node[key])
                if part:
                    return part
        return "\n".join(part for value in node.values() if (part := _flatten_text(value)))
    return str(node)
