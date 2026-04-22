# Unit tests for copilot_insights.summarizer module.
from __future__ import annotations

from copilot_insights.parser import ParsedRequest, ParsedSession, ResponseChunk
from copilot_insights.summarizer import _MAX_SUMMARY_CHARS, summarize_session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    request_id: str = "r1",
    message_text: str = "Hello",
    response_text: str = "World",
) -> ParsedRequest:
    return ParsedRequest(
        request_id=request_id,
        timestamp="2026-04-01T10:00:00.000Z",
        agent="copilot",
        model_id="gpt-4o",
        message_text=message_text,
        response_text=response_text,
        response_chunks=[ResponseChunk(value=response_text, kind="")],
        time_spent_waiting=0.0,
    )


def _make_session(
    session_id: str = "sess-001",
    requests: list[ParsedRequest] | None = None,
) -> ParsedSession:
    return ParsedSession(
        session_id=session_id,
        creation_date="2026-04-01T10:00:00.000Z",
        selected_model="gpt-4o",
        requests=requests or [],
    )


# ---------------------------------------------------------------------------
# Empty session
# ---------------------------------------------------------------------------


def test_empty_session_returns_empty_string() -> None:
    """リクエストが空のセッションは空文字列を返す。"""
    session = _make_session(requests=[])
    assert summarize_session(session) == ""


# ---------------------------------------------------------------------------
# Content inclusion
# ---------------------------------------------------------------------------


def test_summary_contains_session_id() -> None:
    """要約にsession_idが含まれる。"""
    session = _make_session(session_id="my-session-123", requests=[_make_request()])
    summary = summarize_session(session)
    assert "my-session-123" in summary


def test_summary_contains_message_text() -> None:
    """要約にユーザーメッセージのテキスト（先頭部分）が含まれる。"""
    session = _make_session(requests=[_make_request(message_text="Fix the bug in parser")])
    summary = summarize_session(session)
    assert "Fix the bug in parser" in summary


def test_summary_contains_response_text() -> None:
    """要約にアシスタント応答のテキスト（先頭部分）が含まれる。"""
    session = _make_session(requests=[_make_request(response_text="Sure, here is the fix")])
    summary = summarize_session(session)
    assert "Sure, here is the fix" in summary


def test_summary_contains_message_count() -> None:
    """要約にメッセージ数が含まれる。"""
    requests = [_make_request(request_id=f"r{i}") for i in range(3)]
    session = _make_session(requests=requests)
    summary = summarize_session(session)
    assert "3" in summary


# ---------------------------------------------------------------------------
# Length limit (NFR-002: no full text sent)
# ---------------------------------------------------------------------------


def test_summary_respects_max_chars_limit() -> None:
    """要約は _MAX_SUMMARY_CHARS 以内に収まる。"""
    long_msg = "A" * 2000
    long_resp = "B" * 2000
    requests = [_make_request(message_text=long_msg, response_text=long_resp) for _ in range(10)]
    session = _make_session(requests=requests)
    summary = summarize_session(session)
    assert len(summary) <= _MAX_SUMMARY_CHARS


def test_summary_does_not_include_full_long_message() -> None:
    """長いメッセージは切り捨てられ、全文は含まれない。"""
    long_msg = "X" * 1000
    session = _make_session(requests=[_make_request(message_text=long_msg)])
    summary = summarize_session(session)
    assert long_msg not in summary
    assert "X" in summary  # 先頭部分は含まれる


# ---------------------------------------------------------------------------
# Multiple requests
# ---------------------------------------------------------------------------


def test_summary_includes_all_requests_up_to_limit() -> None:
    """複数リクエストが番号付きで含まれる（文字数制限内）。"""
    requests = [
        _make_request(request_id=f"r{i}", message_text=f"Question {i}", response_text=f"Answer {i}")
        for i in range(3)
    ]
    session = _make_session(requests=requests)
    summary = summarize_session(session)
    assert "[1]" in summary
    assert "Question 0" in summary


def test_single_request_no_response() -> None:
    """応答なしのリクエストでもクラッシュしない。"""
    session = _make_session(requests=[_make_request(response_text="")])
    summary = summarize_session(session)
    assert "User:" in summary
