from __future__ import annotations

from app.retrieval.hybrid import RankedCandidate, rrf_fuse, rrf_fuse_with_debug, to_fts_query


def test_to_fts_query_sanitizes_hyphenated_tokens() -> None:
    query = to_fts_query("fact-9006-hawkes")
    assert query == '"fact" "9006" "hawkes"'


def test_to_fts_query_drops_unsafe_chars() -> None:
    query = to_fts_query('port:9006 "hawkes"')
    assert query == '"port" "9006" "hawkes"'


def test_to_fts_query_empty_on_no_tokens() -> None:
    assert to_fts_query(" - : + ") == ""


def test_rrf_fuse_boosts_fact_over_turn_when_rank_is_tied() -> None:
    dense = [
        RankedCandidate(
            chunk_id="turn-1",
            chunk_text="generic dialog",
            chunk_type="turn",
            conversation_id="c1",
            created_at="2026-01-01T00:00:00+00:00",
            importance=0.2,
        )
    ]
    lexical = [
        RankedCandidate(
            chunk_id="fact-1",
            chunk_text="important fact",
            chunk_type="fact",
            conversation_id="c1",
            created_at="2026-01-01T00:00:00+00:00",
            importance=0.2,
        )
    ]
    fused = rrf_fuse(dense, lexical, intent=None)
    assert fused[0].chunk_id == "fact-1"


def test_rrf_fuse_respects_channel_weights() -> None:
    dense = [
        RankedCandidate(
            chunk_id="dense-1",
            chunk_text="dense",
            chunk_type="summary",
            conversation_id="c1",
            created_at="2026-01-01T00:00:00+00:00",
            importance=0.3,
        )
    ]
    lexical = [
        RankedCandidate(
            chunk_id="lex-1",
            chunk_text="lex",
            chunk_type="summary",
            conversation_id="c1",
            created_at="2026-01-01T00:00:00+00:00",
            importance=0.3,
        )
    ]
    fused = rrf_fuse(dense, lexical, intent=None, dense_weight=1.4, lexical_weight=0.6)
    assert fused[0].chunk_id == "dense-1"


def test_rrf_fuse_with_debug_exposes_component_scores() -> None:
    dense = [
        RankedCandidate(
            chunk_id="chunk-1",
            chunk_text="dense signal",
            chunk_type="fact",
            conversation_id="c1",
            created_at="2026-01-01T00:00:00+00:00",
            importance=0.9,
            score=0.77,
        )
    ]
    fused, debug = rrf_fuse_with_debug(dense, [], intent="semantic")
    assert fused[0].chunk_id == "chunk-1"
    assert "chunk-1" in debug
    assert debug["chunk-1"]["dense_similarity"] == 0.77
    assert debug["chunk-1"]["dense_rrf"] > 0
