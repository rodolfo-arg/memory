from app.ingestion.chunker import extract_high_signal_chunks, split_turn_text


def test_split_turn_text_overlaps_large_input() -> None:
    text = "line\n" * 5000
    chunks = split_turn_text(text, max_tokens=200, overlap_tokens=20)
    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)


def test_extract_high_signal_chunks_detects_command_error_decision() -> None:
    text = """
    Decision: we will use sqlite + fts5
    $ pnpm install
    RuntimeError: migration failed
    TODO: add backup workflow
    """
    found = extract_high_signal_chunks(text)
    types = {item.chunk_type for item in found}
    assert "command" in types
    assert "error" in types
    assert "decision" in types
    assert "todo" in types
