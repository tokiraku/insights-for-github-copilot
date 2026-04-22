# Performance benchmark for NFR-001: session-meta extraction of 50 sessions
# must complete within 60 seconds (excluding LLM calls and file I/O).
#
# Run with:
#   pytest -m performance -v tests/test_performance.py
#
# Or include in the regular test run — the test itself enforces the time budget.
from __future__ import annotations

import time

import pytest

from copilot_insights.extractor import extract_session_meta
from copilot_insights.parser import ParsedRequest, ParsedSession, ResponseChunk

# Time budget defined by NFR-001 (LLM calls excluded).
_BUDGET_SECONDS = 60.0

# Number of sessions to benchmark (NFR-001 specifies 50 sessions).
_SESSION_COUNT = 50


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_tool_chunk(tool_name: str, file_path: str) -> ResponseChunk:
    import json

    payload = json.dumps({
        "toolName": tool_name,
        "input": {"file_path": file_path},
        "result": "success",
    })
    return ResponseChunk(kind="toolInvocationSerialized", value=payload)


def _make_request(idx: int) -> ParsedRequest:
    """Build a realistic ParsedRequest with tool invocations and response text."""
    ts_ms = 1700000000000 + idx * 60_000  # 1-minute apart
    chunks = [
        ResponseChunk(kind="markdownContent", value="Here is the implementation.\n" * 20),
        _make_tool_chunk("Edit", f"src/module_{idx % 10}.py"),
        _make_tool_chunk("Read", f"tests/test_module_{idx % 10}.py"),
    ]
    return ParsedRequest(
        request_id=f"req-{idx}",
        timestamp=str(ts_ms),
        agent="copilot",
        model_id="claude-haiku-4-5",
        message_text=f"Please refactor function_{idx} in module_{idx % 10}.py " * 5,
        response_text="Here is the implementation.\n" * 20,
        response_chunks=chunks,
    )


def _make_session(session_idx: int) -> ParsedSession:
    """Build a ParsedSession with 10 requests — representative of a real session."""
    requests = [_make_request(session_idx * 10 + i) for i in range(10)]
    return ParsedSession(
        session_id=f"perf-session-{session_idx:04d}",
        creation_date=f"2026-04-{(session_idx % 28) + 1:02d}T10:00:00Z",
        selected_model="claude-haiku-4-5",
        requests=requests,
    )


# ---------------------------------------------------------------------------
# Benchmark test
# ---------------------------------------------------------------------------


@pytest.mark.performance
def test_session_meta_extraction_50_sessions_within_60s() -> None:
    """NFR-001: extracting session-meta for 50 sessions must complete in < 60 s.

    Only measures CPU-bound extraction; LLM calls and disk I/O are excluded.
    """
    sessions = [_make_session(i) for i in range(_SESSION_COUNT)]

    start = time.perf_counter()
    for session in sessions:
        extract_session_meta(session)
    elapsed = time.perf_counter() - start

    print(f"\n  Extracted {_SESSION_COUNT} sessions in {elapsed:.3f}s  (budget: {_BUDGET_SECONDS}s)")
    assert elapsed < _BUDGET_SECONDS, (
        f"session-meta extraction took {elapsed:.2f}s for {_SESSION_COUNT} sessions "
        f"— exceeds NFR-001 budget of {_BUDGET_SECONDS}s"
    )
