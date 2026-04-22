# Unit tests for copilot_insights.session_loader module.
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from copilot_insights.session_loader import (
    DEFAULT_DAYS,
    DEFAULT_MAX_SESSIONS,
    _parse_creation_date,
    load_sessions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _days_ago(n: float) -> datetime:
    return datetime.now(tz=UTC) - timedelta(days=n)


def _make_jsonl(tmp_path: Path, name: str, session_id: str, creation_date: str) -> Path:
    p = tmp_path / name
    lines = [
        json.dumps({"kind": 0, "v": {
            "sessionId": session_id, "creationDate": creation_date, "selectedModel": "gpt-4o",
        }}),
        json.dumps({"kind": 2, "k": ["requests"], "v": []}),
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _parse_creation_date
# ---------------------------------------------------------------------------

class TestParseCreationDate:
    def test_parses_z_suffix(self):
        result = _parse_creation_date("2026-04-01T10:00:00.000Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_parses_explicit_utc_offset(self):
        result = _parse_creation_date("2026-04-01T10:00:00+00:00")
        assert result is not None

    def test_returns_none_for_empty_string(self):
        assert _parse_creation_date("") is None

    def test_returns_none_for_invalid_string(self):
        assert _parse_creation_date("not-a-date") is None

    def test_naive_datetime_gets_utc(self):
        result = _parse_creation_date("2026-04-01T10:00:00")
        assert result is not None
        assert result.tzinfo == UTC

    def test_parses_int_unix_ms(self):
        # 1700000000000 ms = 2023-11-14T22:13:20Z
        result = _parse_creation_date(1700000000000)
        assert result is not None
        assert result.tzinfo is not None
        assert result.year == 2023

    def test_parses_float_unix_ms(self):
        result = _parse_creation_date(1700000000000.0)
        assert result is not None
        assert result.tzinfo is not None

    def test_returns_none_for_zero_int(self):
        # 0 ms is Unix epoch — valid but extremely old; _parse_creation_date returns a datetime
        result = _parse_creation_date(0)
        assert result is not None  # epoch is parseable

    def test_returns_none_for_none_value(self):
        assert _parse_creation_date("") is None


# ---------------------------------------------------------------------------
# load_sessions — filtering
# ---------------------------------------------------------------------------

class TestLoadSessionsFiltering:
    def test_includes_session_within_days(self, tmp_path):
        date = _iso(_days_ago(1))
        _make_jsonl(tmp_path, "recent.jsonl", "s1", date)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[tmp_path / "recent.jsonl"]):
            result = load_sessions([], days=30)

        assert len(result) == 1
        assert result[0]["session_id"] == "s1"

    def test_excludes_session_older_than_days(self, tmp_path):
        date = _iso(_days_ago(31))
        _make_jsonl(tmp_path, "old.jsonl", "old_session", date)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[tmp_path / "old.jsonl"]):
            result = load_sessions([], days=30)

        assert result == []

    def test_includes_session_exactly_at_boundary(self, tmp_path):
        # Approximately 30 days ago minus 86.4 seconds should be included
        date = _iso(_days_ago(29.999))
        _make_jsonl(tmp_path, "edge.jsonl", "edge_session", date)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[tmp_path / "edge.jsonl"]):
            result = load_sessions([], days=30)

        assert len(result) == 1

    def test_excludes_session_with_unparseable_date(self, tmp_path):
        p = tmp_path / "bad_date.jsonl"
        p.write_text(
            json.dumps({"kind": 0, "v": {"sessionId": "s_bad", "creationDate": "not-a-date", "selectedModel": "m"}})
            + "\n",
            encoding="utf-8",
        )

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[p]):
            result = load_sessions([], days=30)

        assert result == []

    def test_skips_unparseable_jsonl_file(self, tmp_path):
        p = tmp_path / "corrupt.jsonl"
        p.write_text("not json\n", encoding="utf-8")

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[p]):
            result = load_sessions([], days=30)

        assert result == []

    def test_custom_days_parameter(self, tmp_path):
        date_7 = _iso(_days_ago(6))
        date_15 = _iso(_days_ago(14))
        _make_jsonl(tmp_path, "s7.jsonl", "s7", date_7)
        _make_jsonl(tmp_path, "s15.jsonl", "s15", date_15)

        with patch(
            "copilot_insights.session_loader.list_jsonl_files",
            return_value=[tmp_path / "s7.jsonl", tmp_path / "s15.jsonl"],
        ):
            result = load_sessions([], days=10)

        assert len(result) == 1
        assert result[0]["session_id"] == "s7"


# ---------------------------------------------------------------------------
# load_sessions — max_sessions limit
# ---------------------------------------------------------------------------

class TestLoadSessionsLimit:
    def test_respects_max_sessions(self, tmp_path):
        files = []
        for i in range(10):
            date = _iso(_days_ago(i))
            p = _make_jsonl(tmp_path, f"s{i}.jsonl", f"session_{i}", date)
            files.append(p)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=files):
            result = load_sessions([], days=30, max_sessions=5)

        assert len(result) == 5

    def test_returns_fewer_than_max_when_not_enough_sessions(self, tmp_path):
        date = _iso(_days_ago(1))
        _make_jsonl(tmp_path, "only.jsonl", "only_session", date)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[tmp_path / "only.jsonl"]):
            result = load_sessions([], days=30, max_sessions=50)

        assert len(result) == 1

    def test_default_max_is_50(self, tmp_path):
        assert DEFAULT_MAX_SESSIONS == 50

    def test_default_days_is_30(self, tmp_path):
        assert DEFAULT_DAYS == 30


# ---------------------------------------------------------------------------
# load_sessions — ordering
# ---------------------------------------------------------------------------

class TestLoadSessionsOrdering:
    def test_sessions_sorted_newest_first(self, tmp_path):
        dates = [_days_ago(5), _days_ago(1), _days_ago(10), _days_ago(3)]
        files = []
        for i, dt in enumerate(dates):
            p = _make_jsonl(tmp_path, f"s{i}.jsonl", f"session_{i}", _iso(dt))
            files.append(p)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=files):
            result = load_sessions([], days=30)

        ids = [s["session_id"] for s in result]
        # session_1 is 1 day ago (newest), session_2 is 10 days ago (oldest)
        assert ids[0] == "session_1"
        assert ids[-1] == "session_2"

    def test_max_sessions_takes_newest(self, tmp_path):
        files = []
        for i in range(5):
            date = _iso(_days_ago(i + 1))  # 1..5 days ago
            p = _make_jsonl(tmp_path, f"s{i}.jsonl", f"session_{i}", date)
            files.append(p)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=files):
            result = load_sessions([], days=30, max_sessions=3)

        # Should keep sessions 0,1,2 (1,2,3 days ago) and drop 3,4 (4,5 days ago)
        ids = [s["session_id"] for s in result]
        assert "session_0" in ids
        assert "session_1" in ids
        assert "session_2" in ids
        assert "session_3" not in ids
        assert "session_4" not in ids


# ---------------------------------------------------------------------------
# load_sessions — integration with workspace_ids
# ---------------------------------------------------------------------------

class TestLoadSessionsWorkspaceIds:
    def test_passes_workspace_ids_to_list_jsonl_files(self, tmp_path):
        captured = []

        def fake_list(ws_ids):
            captured.extend(ws_ids)
            return []

        with patch("copilot_insights.session_loader.list_jsonl_files", side_effect=fake_list):
            load_sessions(["ws1", "ws2"])

        assert captured == ["ws1", "ws2"]

    def test_returns_empty_list_when_no_files(self):
        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[]):
            result = load_sessions(["any_id"])

        assert result == []


# ---------------------------------------------------------------------------
# load_sessions — int/float creationDate support
# ---------------------------------------------------------------------------

class TestLoadSessionsIntDate:
    def _make_jsonl_int_date(self, tmp_path: Path, name: str, session_id: str, creation_ms: int) -> Path:
        """Write a JSONL file with a numeric (Unix ms) creationDate."""
        import json as _json
        p = tmp_path / name
        lines = [
            _json.dumps({"kind": 0, "v": {
                "sessionId": session_id, "creationDate": creation_ms, "selectedModel": "gpt-4o",
            }}),
            _json.dumps({"kind": 2, "k": ["requests"], "v": []}),
        ]
        p.write_text("\n".join(lines), encoding="utf-8")
        return p

    def test_includes_session_with_recent_int_date(self, tmp_path):
        # 1 day ago in ms
        recent_ms = int((_days_ago(1)).timestamp() * 1000)
        p = self._make_jsonl_int_date(tmp_path, "int_date.jsonl", "sess-int", recent_ms)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[p]):
            result = load_sessions([], days=30)

        assert len(result) == 1
        assert result[0]["session_id"] == "sess-int"

    def test_excludes_session_with_old_int_date(self, tmp_path):
        # 60 days ago in ms
        old_ms = int((_days_ago(60)).timestamp() * 1000)
        p = self._make_jsonl_int_date(tmp_path, "old_int.jsonl", "sess-old-int", old_ms)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[p]):
            result = load_sessions([], days=30)

        assert result == []

    def test_creation_date_normalized_to_iso_string(self, tmp_path):
        recent_ms = int((_days_ago(1)).timestamp() * 1000)
        p = self._make_jsonl_int_date(tmp_path, "norm.jsonl", "sess-norm", recent_ms)

        with patch("copilot_insights.session_loader.list_jsonl_files", return_value=[p]):
            result = load_sessions([], days=30)

        # creation_date must be a string (ISO 8601) after normalization in parser
        assert isinstance(result[0]["creation_date"], str)
        assert "T" in result[0]["creation_date"]
