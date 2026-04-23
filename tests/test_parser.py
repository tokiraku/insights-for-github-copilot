# Unit tests for copilot_insights.parser module.
from __future__ import annotations

import json
from pathlib import Path

from copilot_insights.parser import parse_jsonl_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(tmp_path: Path, name: str, lines: list[dict]) -> Path:
    """Write a list of dicts as a JSONL file and return its path."""
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return p


def _init_line(
    session_id: str = "sess-001",
    creation_date: str = "2026-04-01T10:00:00.000Z",
    selected_model: str = "gpt-4o",
) -> dict:
    return {
        "kind": 0,
        "v": {
            "sessionId": session_id,
            "creationDate": creation_date,
            "selectedModel": selected_model,
        },
    }


def _snapshot_line(requests: list[dict]) -> dict:
    return {"kind": 2, "k": ["requests"], "v": requests}


def _response_patch_line(index: int, chunks: list[dict]) -> dict:
    return {"kind": 2, "k": ["requests", index, "response"], "v": chunks}


def _request(
    request_id: str = "req-1",
    timestamp: str = "2026-04-01T10:01:00.000Z",
    message_text: str = "Hello",
    response: list[dict] | None = None,
) -> dict:
    return {
        "requestId": request_id,
        "timestamp": timestamp,
        "agent": "copilot",
        "modelId": "gpt-4o",
        "message": {"text": message_text},
        "response": response or [],
        "timeSpentWaiting": 1200.0,
    }


# ---------------------------------------------------------------------------
# parse_jsonl_file — basic success cases
# ---------------------------------------------------------------------------

class TestParseJsonlFileBasic:
    def test_returns_session_with_correct_metadata(self, tmp_path):
        path = _write_jsonl(tmp_path, "session.jsonl", [
            _init_line(session_id="s1", creation_date="2026-04-01T10:00:00Z", selected_model="gpt-4o"),
            _snapshot_line([]),
        ])
        result = parse_jsonl_file(path)
        assert result is not None
        assert result["session_id"] == "s1"
        assert result["creation_date"] == "2026-04-01T10:00:00Z"
        assert result["selected_model"] == "gpt-4o"

    def test_returns_none_when_no_init_line(self, tmp_path):
        path = _write_jsonl(tmp_path, "no_init.jsonl", [
            _snapshot_line([_request()])
        ])
        assert parse_jsonl_file(path) is None

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        assert parse_jsonl_file(tmp_path / "missing.jsonl") is None

    def test_returns_none_for_non_json_content(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        path.write_text("not json at all\n", encoding="utf-8")
        result = parse_jsonl_file(path)
        # No valid kind=0 line → None
        assert result is None

    def test_returns_none_when_read_text_raises_os_error(self, tmp_path, monkeypatch):
        path = tmp_path / "unreadable.jsonl"
        path.write_text("placeholder", encoding="utf-8")

        def _raise_os_error(self, *args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", _raise_os_error)
        assert parse_jsonl_file(path) is None

    def test_returns_none_when_read_text_raises_unicode_decode_error(self, tmp_path, monkeypatch):
        path = tmp_path / "binary.jsonl"
        path.write_text("placeholder", encoding="utf-8")

        def _raise_unicode_error(self, *args, **kwargs):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "invalid byte")

        monkeypatch.setattr(Path, "read_text", _raise_unicode_error)
        assert parse_jsonl_file(path) is None

    def test_empty_requests_when_no_snapshot(self, tmp_path):
        path = _write_jsonl(tmp_path, "session.jsonl", [
            _init_line(),
        ])
        result = parse_jsonl_file(path)
        assert result is not None
        assert result["requests"] == []


# ---------------------------------------------------------------------------
# parse_jsonl_file — request extraction
# ---------------------------------------------------------------------------

class TestParseJsonlFileRequests:
    def test_extracts_message_text(self, tmp_path):
        req = _request(message_text="What is Python?")
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
        ])
        result = parse_jsonl_file(path)
        assert result["requests"][0]["message_text"] == "What is Python?"

    def test_extracts_markdown_response_from_snapshot(self, tmp_path):
        req = _request(response=[{"value": "Python is great."}])
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
        ])
        result = parse_jsonl_file(path)
        assert result["requests"][0]["response_text"] == "Python is great."

    def test_concatenates_multiple_markdown_chunks(self, tmp_path):
        req = _request(response=[
            {"value": "Hello "},
            {"value": "world."},
        ])
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
        ])
        result = parse_jsonl_file(path)
        assert result["requests"][0]["response_text"] == "Hello world."

    def test_excludes_non_markdown_chunks_from_response_text(self, tmp_path):
        req = _request(response=[
            {"value": "Answer.", "kind": "markdownContent"},
            {"value": "<tool>", "kind": "toolInvocationSerialized"},
            {"value": "thinking...", "kind": "thinking"},
        ])
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
        ])
        result = parse_jsonl_file(path)
        assert result["requests"][0]["response_text"] == "Answer."

    def test_extracts_request_metadata(self, tmp_path):
        req = _request(request_id="r1", timestamp="2026-04-01T10:05:00Z")
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
        ])
        result = parse_jsonl_file(path)
        r = result["requests"][0]
        assert r["request_id"] == "r1"
        assert r["timestamp"] == "2026-04-01T10:05:00Z"
        assert r["agent"] == "copilot"
        assert r["model_id"] == "gpt-4o"
        assert r["time_spent_waiting"] == 1200.0

    def test_multiple_requests_preserved(self, tmp_path):
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([
                _request(request_id="r1", message_text="Q1"),
                _request(request_id="r2", message_text="Q2"),
            ]),
        ])
        result = parse_jsonl_file(path)
        assert len(result["requests"]) == 2
        assert result["requests"][0]["request_id"] == "r1"
        assert result["requests"][1]["request_id"] == "r2"


# ---------------------------------------------------------------------------
# parse_jsonl_file — kind=2 snapshot / patch semantics
# ---------------------------------------------------------------------------

class TestParseJsonlFileSnapshotSemantics:
    def test_last_snapshot_wins(self, tmp_path):
        """Later k=["requests"] snapshot replaces earlier one."""
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([_request(request_id="old", message_text="old")]),
            _snapshot_line([_request(request_id="new", message_text="new")]),
        ])
        result = parse_jsonl_file(path)
        assert len(result["requests"]) == 1
        assert result["requests"][0]["request_id"] == "new"

    def test_response_patch_appended_to_snapshot_response(self, tmp_path):
        """k=["requests", 0, "response"] chunks are appended to the request."""
        req = _request(response=[{"value": "Part1 "}])
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
            _response_patch_line(0, [{"value": "Part2."}]),
        ])
        result = parse_jsonl_file(path)
        assert result["requests"][0]["response_text"] == "Part1 Part2."

    def test_multiple_response_patches_accumulated(self, tmp_path):
        req = _request(response=[])
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
            _response_patch_line(0, [{"value": "A"}]),
            _response_patch_line(0, [{"value": "B"}]),
            _response_patch_line(0, [{"value": "C"}]),
        ])
        result = parse_jsonl_file(path)
        assert result["requests"][0]["response_text"] == "ABC"

    def test_patches_reset_on_new_snapshot(self, tmp_path):
        """Response patches collected before a new snapshot are discarded."""
        req_old = _request(request_id="old", response=[])
        req_new = _request(request_id="new", response=[{"value": "Fresh."}])
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req_old]),
            _response_patch_line(0, [{"value": "Stale patch"}]),
            _snapshot_line([req_new]),  # resets everything
        ])
        result = parse_jsonl_file(path)
        assert len(result["requests"]) == 1
        assert result["requests"][0]["request_id"] == "new"
        assert result["requests"][0]["response_text"] == "Fresh."

    def test_patch_for_out_of_bounds_index_is_ignored(self, tmp_path):
        req = _request(response=[])
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
            _response_patch_line(99, [{"value": "ghost"}]),  # index 99 doesn't exist
        ])
        result = parse_jsonl_file(path)
        assert result["requests"][0]["response_text"] == ""

    def test_kind1_lines_are_ignored(self, tmp_path):
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            {"kind": 1, "v": {"inputText": "user is typing..."}},
            _snapshot_line([_request(request_id="r1")]),
        ])
        result = parse_jsonl_file(path)
        assert len(result["requests"]) == 1

    def test_invalid_json_lines_are_skipped(self, tmp_path):
        p = tmp_path / "s.jsonl"
        lines = [
            json.dumps(_init_line()),
            "{ this is not valid json }",
            json.dumps(_snapshot_line([_request(request_id="r1")])),
        ]
        p.write_text("\n".join(lines), encoding="utf-8")
        result = parse_jsonl_file(p)
        assert result is not None
        assert len(result["requests"]) == 1


# ---------------------------------------------------------------------------
# parse_jsonl_file — response_chunks field
# ---------------------------------------------------------------------------

class TestParseJsonlFileResponseChunks:
    def test_response_chunks_include_all_kinds(self, tmp_path):
        req = _request(response=[
            {"value": "Answer.", "kind": "markdownContent"},
            {"value": "<tool>", "kind": "toolInvocationSerialized"},
        ])
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
        ])
        result = parse_jsonl_file(path)
        chunks = result["requests"][0]["response_chunks"]
        assert len(chunks) == 2
        kinds = {c["kind"] for c in chunks}
        assert "markdownContent" in kinds
        assert "toolInvocationSerialized" in kinds

    def test_chunk_without_kind_gets_empty_string(self, tmp_path):
        req = _request(response=[{"value": "plain markdown"}])
        path = _write_jsonl(tmp_path, "s.jsonl", [
            _init_line(),
            _snapshot_line([req]),
        ])
        result = parse_jsonl_file(path)
        chunk = result["requests"][0]["response_chunks"][0]
        assert chunk["kind"] == ""
        assert chunk["value"] == "plain markdown"


# ---------------------------------------------------------------------------
# parse_jsonl_file — workspace_id propagation
# ---------------------------------------------------------------------------

class TestParseJsonlFileWorkspaceId:
    def test_workspace_id_defaults_to_empty_string(self, tmp_path):
        path = _write_jsonl(tmp_path, "s.jsonl", [_init_line(), _snapshot_line([])])
        result = parse_jsonl_file(path)
        assert result is not None
        assert result["workspace_id"] == ""

    def test_workspace_id_propagated_when_provided(self, tmp_path):
        path = _write_jsonl(tmp_path, "s.jsonl", [_init_line(), _snapshot_line([])])
        result = parse_jsonl_file(path, workspace_id="abc123")
        assert result is not None
        assert result["workspace_id"] == "abc123"

    def test_workspace_id_in_session_loaded_via_session_loader(self, tmp_path):
        from unittest.mock import patch
        from datetime import UTC, datetime, timedelta
        from copilot_insights.session_loader import load_sessions

        date = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        path = _write_jsonl(tmp_path, "s.jsonl", [_init_line(creation_date=date), _snapshot_line([])])

        with patch(
            "copilot_insights.session_loader.list_jsonl_files_with_ids",
            return_value=[("my_ws_id", path)],
        ):
            sessions = load_sessions([], days=365)

        assert len(sessions) == 1
        assert sessions[0]["workspace_id"] == "my_ws_id"
