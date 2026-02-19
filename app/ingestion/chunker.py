from __future__ import annotations

import re
from dataclasses import dataclass


def approximate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class ChunkUnit:
    chunk_text: str
    chunk_type: str
    importance: float


def split_turn_text(text: str, max_tokens: int = 600, overlap_tokens: int = 80) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []

    max_chars = max_tokens * 4
    overlap_chars = overlap_tokens * 4

    if len(cleaned) <= max_chars:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + max_chars)
        if end < len(cleaned):
            pivot = cleaned.rfind("\n", start, end)
            if pivot != -1 and pivot > start + max_chars // 2:
                end = pivot
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        start = max(0, end - overlap_chars)

    return chunks


def extract_high_signal_chunks(text: str) -> list[ChunkUnit]:
    units: list[ChunkUnit] = []

    units.extend(_extract_command_chunks(text))
    units.extend(_extract_error_chunks(text))
    units.extend(_extract_decision_chunks(text))
    units.extend(_extract_todo_chunks(text))

    seen: set[tuple[str, str]] = set()
    deduped: list[ChunkUnit] = []
    for unit in units:
        key = (unit.chunk_type, unit.chunk_text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(unit)
    return deduped


def _extract_command_chunks(text: str) -> list[ChunkUnit]:
    results: list[ChunkUnit] = []
    line_commands = re.findall(r"(?m)^\s*\$\s+(.+)$", text)
    for cmd in line_commands:
        results.append(ChunkUnit(chunk_text=cmd.strip(), chunk_type="command", importance=0.80))

    fenced = re.findall(r"```(?:bash|sh|zsh)?\n([\s\S]*?)```", text)
    for block in fenced:
        for line in block.splitlines():
            stripped = line.strip()
            if stripped:
                results.append(
                    ChunkUnit(chunk_text=stripped, chunk_type="command", importance=0.75)
                )

    return results


def _extract_error_chunks(text: str) -> list[ChunkUnit]:
    pattern = re.compile(
        r"(?im)(error|exception|traceback|failed|failure|panic|stack trace)[^\n]*"
    )
    return [
        ChunkUnit(chunk_text=match.group(0).strip(), chunk_type="error", importance=0.70)
        for match in pattern.finditer(text)
    ]


def _extract_decision_chunks(text: str) -> list[ChunkUnit]:
    pattern = re.compile(
        r"(?im)(decision|decided|chosen approach|we will|let's use|selected)[:\-\s].{0,220}"
    )
    return [
        ChunkUnit(chunk_text=match.group(0).strip(), chunk_type="decision", importance=0.90)
        for match in pattern.finditer(text)
    ]


def _extract_todo_chunks(text: str) -> list[ChunkUnit]:
    pattern = re.compile(r"(?im)(todo|next step|follow up|action item)[:\-\s].{0,220}")
    return [
        ChunkUnit(chunk_text=match.group(0).strip(), chunk_type="todo", importance=0.60)
        for match in pattern.finditer(text)
    ]
