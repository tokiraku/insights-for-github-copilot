# Unit tests for copilot_insights.extractor and copilot_insights.writer modules.
from __future__ import annotations

import json

import pytest

from copilot_insights.extractor import extract_session_meta
from copilot_insights.models import SCHEMA_VERSION
from copilot_insights.parser import ParsedRequest, ParsedSession, ResponseChunk
from copilot_insights.writer import write_facets, write_session_meta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(value: str, kind: str = "") -> ResponseChunk:
    return ResponseChunk(value=value, kind=kind)


def _tool_chunk(invocation: dict) -> ResponseChunk:
    """Build a toolInvocationSerialized chunk from a dict."""
    return ResponseChunk(value=json.dumps(invocation), kind="toolInvocationSerialized")


def _make_request(
    request_id: str = "r1",
    timestamp: str | float = "2026-04-01T10:00:00.000Z",
    message_text: str = "Hello",
    response_text: str = "World",
    response_chunks: list[ResponseChunk] | None = None,
    time_spent_waiting: float = 0.0,
) -> ParsedRequest:
    return ParsedRequest(
        request_id=request_id,
        timestamp=str(timestamp) if isinstance(timestamp, float) else timestamp,
        agent="copilot",
        model_id="gpt-4o",
        message_text=message_text,
        response_text=response_text,
        response_chunks=response_chunks or [],
        time_spent_waiting=time_spent_waiting,
    )


def _make_session(
    session_id: str = "sess-001",
    creation_date: str = "2026-04-01T10:00:00.000Z",
    requests: list[ParsedRequest] | None = None,
) -> ParsedSession:
    return ParsedSession(
        session_id=session_id,
        creation_date=creation_date,
        selected_model="gpt-4o",
        requests=requests or [],
    )


# ---------------------------------------------------------------------------
# extract_session_meta — schema_version and session_id
# ---------------------------------------------------------------------------

class TestSchemaVersionAndSessionId:
    def test_schema_version_is_set(self):
        meta = extract_session_meta(_make_session())
        assert meta["schema_version"] == SCHEMA_VERSION

    def test_session_id_matches_input(self):
        meta = extract_session_meta(_make_session(session_id="abc-123"))
        assert meta["session_id"] == "abc-123"

    def test_start_time_matches_creation_date(self):
        meta = extract_session_meta(_make_session(creation_date="2026-04-01T09:00:00Z"))
        assert meta["start_time"] == "2026-04-01T09:00:00Z"


# ---------------------------------------------------------------------------
# extract_session_meta — user_message_count
# ---------------------------------------------------------------------------

class TestUserMessageCount:
    def test_zero_requests(self):
        meta = extract_session_meta(_make_session(requests=[]))
        assert meta["user_message_count"] == 0

    def test_single_request(self):
        meta = extract_session_meta(_make_session(requests=[_make_request()]))
        assert meta["user_message_count"] == 1

    def test_multiple_requests(self):
        reqs = [_make_request(request_id=f"r{i}") for i in range(5)]
        meta = extract_session_meta(_make_session(requests=reqs))
        assert meta["user_message_count"] == 5


# ---------------------------------------------------------------------------
# extract_session_meta — duration_minutes and user_response_times
# ---------------------------------------------------------------------------

class TestDurationAndResponseTimes:
    def test_zero_duration_when_no_requests(self):
        meta = extract_session_meta(_make_session(requests=[]))
        assert meta["duration_minutes"] == 0.0

    def test_zero_duration_when_single_request(self):
        meta = extract_session_meta(_make_session(requests=[_make_request()]))
        assert meta["duration_minutes"] == 0.0

    def test_duration_computed_from_iso_timestamps(self):
        reqs = [
            _make_request(request_id="r1", timestamp="2026-04-01T10:00:00.000Z"),
            _make_request(request_id="r2", timestamp="2026-04-01T10:05:00.000Z"),
        ]
        meta = extract_session_meta(_make_session(requests=reqs))
        assert meta["duration_minutes"] == pytest.approx(5.0, abs=0.01)

    def test_duration_computed_from_unix_ms_timestamps(self):
        # 10 minutes = 600000 ms
        t0 = 1_743_508_800_000.0  # arbitrary epoch ms
        t1 = t0 + 600_000.0
        reqs = [
            _make_request(request_id="r1", timestamp=str(t0)),
            _make_request(request_id="r2", timestamp=str(t1)),
        ]
        meta = extract_session_meta(_make_session(requests=reqs))
        assert meta["duration_minutes"] == pytest.approx(10.0, abs=0.01)

    def test_user_response_times_empty_when_single_request(self):
        meta = extract_session_meta(_make_session(requests=[_make_request()]))
        assert meta["user_response_times"] == []

    def test_user_response_times_between_consecutive_messages(self):
        reqs = [
            _make_request(request_id="r1", timestamp="2026-04-01T10:00:00.000Z"),
            _make_request(request_id="r2", timestamp="2026-04-01T10:01:00.000Z"),
            _make_request(request_id="r3", timestamp="2026-04-01T10:01:30.000Z"),
        ]
        meta = extract_session_meta(_make_session(requests=reqs))
        assert len(meta["user_response_times"]) == 2
        assert meta["user_response_times"][0] == pytest.approx(60.0, abs=0.01)
        assert meta["user_response_times"][1] == pytest.approx(30.0, abs=0.01)

    def test_unparseable_timestamps_are_skipped(self):
        reqs = [
            _make_request(request_id="r1", timestamp="not-a-date"),
            _make_request(request_id="r2", timestamp="also-invalid"),
        ]
        meta = extract_session_meta(_make_session(requests=reqs))
        assert meta["duration_minutes"] == 0.0
        assert meta["user_response_times"] == []


# ---------------------------------------------------------------------------
# extract_session_meta — message_hours
# ---------------------------------------------------------------------------

class TestMessageHours:
    def test_empty_when_no_requests(self):
        meta = extract_session_meta(_make_session(requests=[]))
        assert meta["message_hours"] == []

    def test_hours_extracted_from_iso_timestamps(self):
        reqs = [
            _make_request(request_id="r1", timestamp="2026-04-01T09:30:00.000Z"),
            _make_request(request_id="r2", timestamp="2026-04-01T22:15:00.000Z"),
        ]
        meta = extract_session_meta(_make_session(requests=reqs))
        assert meta["message_hours"] == [9, 22]

    def test_hours_from_unix_ms(self):
        # 2026-04-01T00:00:00Z = 1743465600000 ms
        midnight_ms = 1_743_465_600_000.0
        reqs = [_make_request(timestamp=str(midnight_ms))]
        meta = extract_session_meta(_make_session(requests=reqs))
        assert meta["message_hours"] == [0]


# ---------------------------------------------------------------------------
# extract_session_meta — tool_counts
# ---------------------------------------------------------------------------

class TestToolCounts:
    def test_empty_when_no_tool_chunks(self):
        req = _make_request(response_chunks=[_make_chunk("answer", "markdownContent")])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["tool_counts"] == {}

    def test_counts_tool_by_toolName_key(self):
        chunk = _tool_chunk({"toolName": "Read", "input": {}})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["tool_counts"] == {"Read": 1}

    def test_counts_tool_by_name_key_fallback(self):
        chunk = _tool_chunk({"name": "Bash", "input": {}})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["tool_counts"] == {"Bash": 1}

    def test_aggregates_counts_across_requests(self):
        chunks = [
            _tool_chunk({"toolName": "Read", "input": {}}),
            _tool_chunk({"toolName": "Read", "input": {}}),
            _tool_chunk({"toolName": "Write", "input": {}}),
        ]
        reqs = [_make_request(response_chunks=chunks[:2]), _make_request(response_chunks=[chunks[2]])]
        meta = extract_session_meta(_make_session(requests=reqs))
        assert meta["tool_counts"]["Read"] == 2
        assert meta["tool_counts"]["Write"] == 1

    def test_ignores_invalid_json_in_tool_chunk(self):
        bad_chunk = ResponseChunk(value="not json", kind="toolInvocationSerialized")
        req = _make_request(response_chunks=[bad_chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["tool_counts"] == {}


# ---------------------------------------------------------------------------
# extract_session_meta — tool_errors
# ---------------------------------------------------------------------------

class TestToolErrors:
    def test_zero_errors_when_no_tool_chunks(self):
        meta = extract_session_meta(_make_session(requests=[_make_request()]))
        assert meta["tool_errors"] == 0

    def test_detects_string_error_result(self):
        chunk = _tool_chunk({"toolName": "Bash", "result": "error: command not found"})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["tool_errors"] == 1

    def test_detects_dict_isError_result(self):
        chunk = _tool_chunk({"toolName": "Read", "result": {"isError": True, "message": "Not found"}})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["tool_errors"] == 1

    def test_no_error_for_successful_result(self):
        chunk = _tool_chunk({"toolName": "Read", "result": "file contents here"})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["tool_errors"] == 0


# ---------------------------------------------------------------------------
# extract_session_meta — files_modified and languages
# ---------------------------------------------------------------------------

class TestFilesAndLanguages:
    def test_empty_when_no_file_paths(self):
        chunk = _tool_chunk({"toolName": "Bash", "input": {"command": "ls"}})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["files_modified"] == []
        assert meta["languages"] == []

    def test_extracts_file_path_key(self):
        chunk = _tool_chunk({"toolName": "Read", "input": {"file_path": "src/main.py"}})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert "src/main.py" in meta["files_modified"]
        assert "Python" in meta["languages"]

    def test_extracts_path_key(self):
        chunk = _tool_chunk({"toolName": "Write", "input": {"path": "index.ts", "content": "export {}\n"}})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert "index.ts" in meta["files_modified"]
        assert "TypeScript" in meta["languages"]

    def test_deduplicates_files(self):
        chunks = [
            _tool_chunk({"toolName": "Read", "input": {"file_path": "src/app.py"}}),
            _tool_chunk({"toolName": "Write", "input": {"file_path": "src/app.py", "content": "x\n"}}),
        ]
        req = _make_request(response_chunks=chunks)
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["files_modified"].count("src/app.py") == 1

    def test_languages_sorted_by_frequency(self):
        chunks = [
            _tool_chunk({"toolName": "Read", "input": {"file_path": "a.py"}}),
            _tool_chunk({"toolName": "Read", "input": {"file_path": "b.py"}}),
            _tool_chunk({"toolName": "Read", "input": {"file_path": "c.ts"}}),
        ]
        req = _make_request(response_chunks=chunks)
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["languages"][0] == "Python"  # 2 occurrences vs TypeScript's 1

    def test_unknown_extension_capitalized(self):
        chunk = _tool_chunk({"toolName": "Write", "input": {"file_path": "config.xyz"}})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert "Xyz" in meta["languages"]


# ---------------------------------------------------------------------------
# extract_session_meta — lines_added / lines_removed
# ---------------------------------------------------------------------------

class TestDiffLines:
    def test_zeros_when_no_tool_chunks(self):
        meta = extract_session_meta(_make_session(requests=[_make_request()]))
        assert meta["lines_added"] == 0
        assert meta["lines_removed"] == 0

    def test_write_tool_counts_content_lines_as_added(self):
        # 3 lines: "line1\nline2\nline3"
        chunk = _tool_chunk({"toolName": "Write", "input": {"content": "line1\nline2\nline3"}})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["lines_added"] == 3
        assert meta["lines_removed"] == 0

    def test_edit_tool_counts_new_and_old_strings(self):
        chunk = _tool_chunk({
            "toolName": "Edit",
            "input": {
                "new_string": "a\nb\nc",
                "old_string": "x\ny",
            },
        })
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["lines_added"] == 3
        assert meta["lines_removed"] == 2

    def test_diff_field_parsed_correctly(self):
        diff = "+++ b/file.py\n+added line\n-removed line\n--- a/file.py\n context"
        chunk = _tool_chunk({"toolName": "Patch", "input": {"diff": diff}})
        req = _make_request(response_chunks=[chunk])
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["lines_added"] == 1
        assert meta["lines_removed"] == 1


# ---------------------------------------------------------------------------
# extract_session_meta — input_tokens / output_tokens
# ---------------------------------------------------------------------------

class TestTokenEstimates:
    def test_minimum_one_token_when_no_text(self):
        meta = extract_session_meta(_make_session(requests=[_make_request(message_text="", response_text="")]))
        assert meta["input_tokens"] >= 1
        assert meta["output_tokens"] >= 1

    def test_tokens_proportional_to_text_length(self):
        # 40 char input → ~10 tokens; 80 char output → ~20 tokens
        msg = "a" * 40
        resp = "b" * 80
        req = _make_request(message_text=msg, response_text=resp)
        meta = extract_session_meta(_make_session(requests=[req]))
        assert meta["input_tokens"] == 10
        assert meta["output_tokens"] == 20

    def test_tokens_summed_across_requests(self):
        reqs = [
            _make_request(request_id="r1", message_text="a" * 40, response_text="b" * 40),
            _make_request(request_id="r2", message_text="c" * 40, response_text="d" * 40),
        ]
        meta = extract_session_meta(_make_session(requests=reqs))
        assert meta["input_tokens"] == 20
        assert meta["output_tokens"] == 20


# ---------------------------------------------------------------------------
# write_session_meta — file output and schema_version
# ---------------------------------------------------------------------------

class TestWriteSessionMeta:
    def test_creates_output_directory_if_missing(self, tmp_path):
        meta = extract_session_meta(_make_session(session_id="abc"))
        dest = write_session_meta(tmp_path / "new_dir", meta)
        assert dest.exists()

    def test_file_is_in_session_meta_subdir(self, tmp_path):
        meta = extract_session_meta(_make_session(session_id="sid"))
        dest = write_session_meta(tmp_path, meta)
        assert dest.parent.name == "session-meta"

    def test_filename_is_session_id_dot_json(self, tmp_path):
        meta = extract_session_meta(_make_session(session_id="my-session"))
        dest = write_session_meta(tmp_path, meta)
        assert dest.name == "my-session.json"

    def test_output_contains_schema_version(self, tmp_path):
        meta = extract_session_meta(_make_session(session_id="v-test"))
        write_session_meta(tmp_path, meta)
        data = json.loads((tmp_path / "session-meta" / "v-test.json").read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION

    def test_output_json_is_valid_and_complete(self, tmp_path):
        session = _make_session(
            session_id="full",
            requests=[_make_request(message_text="hi", response_text="hello")],
        )
        meta = extract_session_meta(session)
        write_session_meta(tmp_path, meta)
        data = json.loads((tmp_path / "session-meta" / "full.json").read_text(encoding="utf-8"))
        required_keys = {
            "schema_version", "session_id", "start_time", "duration_minutes",
            "user_message_count", "tool_counts", "languages", "input_tokens",
            "output_tokens", "lines_added", "lines_removed", "files_modified",
            "tool_errors", "user_response_times", "message_hours",
        }
        assert required_keys.issubset(data.keys())

    def test_overwrites_existing_file(self, tmp_path):
        meta_v1 = extract_session_meta(_make_session(session_id="ow"))
        write_session_meta(tmp_path, meta_v1)

        session2 = _make_session(session_id="ow", requests=[_make_request(message_text="x" * 100)])
        meta_v2 = extract_session_meta(session2)
        write_session_meta(tmp_path, meta_v2)

        data = json.loads((tmp_path / "session-meta" / "ow.json").read_text(encoding="utf-8"))
        assert data["input_tokens"] == meta_v2["input_tokens"]

    def test_path_traversal_chars_are_stripped(self, tmp_path):
        # "../escape" → sanitized to "escape"; must stay within session-meta/
        meta = extract_session_meta(_make_session(session_id="../escape"))
        dest = write_session_meta(tmp_path, meta)
        assert dest.parent == tmp_path / "session-meta"
        assert dest.name == "escape.json"

    def test_all_unsafe_chars_in_session_id_raises(self, tmp_path):
        meta = extract_session_meta(_make_session(session_id="../../"))
        with pytest.raises(ValueError):
            write_session_meta(tmp_path, meta)


# ---------------------------------------------------------------------------
# write_facets — file output and schema_version
# ---------------------------------------------------------------------------

class TestWriteFacets:
    def _make_facets(self, session_id: str = "f-001") -> dict:
        from copilot_insights.models import SCHEMA_VERSION
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "project_area": "test",
            "primary_goal": "testing",
            "session_type": "Single Task",
            "inferred_satisfaction": "Likely Satisfied",
            "wins": [],
            "frictions": [],
            "suggested_rules": [],
            "suggested_patterns": [],
        }

    def test_creates_output_directory_if_missing(self, tmp_path):
        facets = self._make_facets()
        dest = write_facets(tmp_path / "new_dir", facets)
        assert dest.exists()

    def test_file_is_in_facets_subdir(self, tmp_path):
        facets = self._make_facets(session_id="sid")
        dest = write_facets(tmp_path, facets)
        assert dest.parent.name == "facets"

    def test_filename_is_session_id_dot_json(self, tmp_path):
        facets = self._make_facets(session_id="my-facet")
        dest = write_facets(tmp_path, facets)
        assert dest.name == "my-facet.json"

    def test_output_contains_schema_version(self, tmp_path):
        facets = self._make_facets(session_id="v-test")
        write_facets(tmp_path, facets)
        data = json.loads((tmp_path / "facets" / "v-test.json").read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION

    def test_output_json_is_valid_and_complete(self, tmp_path):
        facets = self._make_facets(session_id="full")
        write_facets(tmp_path, facets)
        data = json.loads((tmp_path / "facets" / "full.json").read_text(encoding="utf-8"))
        required_keys = {
            "schema_version", "session_id", "project_area", "primary_goal",
            "session_type", "inferred_satisfaction", "wins", "frictions",
            "suggested_rules", "suggested_patterns",
        }
        assert required_keys.issubset(data.keys())

    def test_overwrites_existing_file(self, tmp_path):
        facets_v1 = self._make_facets(session_id="ow")
        write_facets(tmp_path, facets_v1)

        facets_v2 = self._make_facets(session_id="ow")
        facets_v2["primary_goal"] = "updated goal"
        write_facets(tmp_path, facets_v2)

        data = json.loads((tmp_path / "facets" / "ow.json").read_text(encoding="utf-8"))
        assert data["primary_goal"] == "updated goal"

    def test_path_traversal_chars_are_stripped(self, tmp_path):
        # "../escape" → sanitized to "escape"; must stay within facets/
        facets = self._make_facets(session_id="../escape")
        dest = write_facets(tmp_path, facets)
        assert dest.parent == tmp_path / "facets"
        assert dest.name == "escape.json"
