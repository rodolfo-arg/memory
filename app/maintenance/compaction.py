from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompactionResult:
    scanned_chunks: int
    compacted_chunks: int
    summary_chunks_created: int


def summarize_chunks(texts: list[str], max_chars: int = 1800) -> str:
    if not texts:
        return ""

    lines: list[str] = ["Compacted memory summary:"]
    for text in texts:
        snippet = " ".join(text.strip().split())
        if not snippet:
            continue
        lines.append(f"- {snippet[:220]}")
        if sum(len(line) for line in lines) >= max_chars:
            break

    return "\n".join(lines)[:max_chars]
