# Integration tests for the full CLI pipeline (INFRA-002).
# Covers: run() orchestration — workspace resolution, session-meta extraction,
# facets generation, and output file creation under .copilot-insights/.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from copilot_insights.__main__ import run
from copilot_insights.models import SCHEMA_VERSION
from copilot_insights.parser import ParsedRequest, ParsedSession, ResponseChunk

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_FACETS_RESPONSE: dict[str, Any] = {
    "project_area": "backend API",
    "primary_goal": "Implement REST endpoint",
    "session_type": "feature_development",
    "inferred_satisfaction": "high",
    "wins": ["Endpoint implemented"],
    "frictions": [],
    "suggested_rules": [],
    "suggested_patterns": [],
}


def _make_request(ts: str = "1700000000000", msg: str = "Hello") -> ParsedRequest:
    return ParsedRequest(
        request_id="req-1",
        timestamp=ts,
        agent="copilot",
        model_id="gpt-4",
        message_text=msg,
        response_text="OK",
        response_chunks=[ResponseChunk(kind="markdownContent", value="OK")],
    )


def _make_session(session_id: str = "sess-abc", creation_date: str = "2026-04-20T10:00:00Z") -> ParsedSession:
    return ParsedSession(
        session_id=session_id,
        creation_date=creation_date,
        selected_model="gpt-4",
        requests=[_make_request()],
    )


# ---------------------------------------------------------------------------
# Helpers: mock load_sessions and LLM
# ---------------------------------------------------------------------------


def _patch_load_sessions(sessions: list[ParsedSession]):
    return patch("copilot_insights.__main__.load_sessions", return_value=sessions)


def _patch_resolve_workspace_ids(ids: list[str]):
    return patch("copilot_insights.__main__.resolve_workspace_ids", return_value=ids)


def _patch_get_workspace_ids(ids: list[str]):
    return patch("copilot_insights.__main__.get_workspace_ids", return_value=ids)


def _make_mock_llm(facets_data: dict[str, Any] | None = None) -> MagicMock:
    """Return a mock AnthropicClient whose generate_facets_from_session returns valid Facets."""
    from copilot_insights.models import Facets

    data = facets_data or _VALID_FACETS_RESPONSE
    mock = MagicMock()
    mock.generate_facets_from_session.return_value = Facets(
        schema_version=SCHEMA_VERSION,
        session_id="sess-abc",
        **{k: data[k] for k in data},
    )
    return mock


# ---------------------------------------------------------------------------
# run() — workspace resolution failures
# ---------------------------------------------------------------------------


class TestRunWorkspaceResolution:
    def test_returns_1_when_no_workspace_ids_found(self, tmp_path: Path) -> None:
        with _patch_resolve_workspace_ids([]):
            result = run(days=30, skip_llm=True, all_workspaces=False, workspace=tmp_path)
        assert result == 1

    def test_returns_1_when_all_workspaces_finds_nothing(self, tmp_path: Path) -> None:
        with _patch_get_workspace_ids([]), _patch_load_sessions([]):
            result = run(days=30, skip_llm=True, all_workspaces=True, workspace=None)
        assert result == 1

    def test_returns_0_when_no_sessions_in_period(self, tmp_path: Path) -> None:
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions([]):
            result = run(days=30, skip_llm=True, all_workspaces=False, workspace=tmp_path)
        assert result == 0


# ---------------------------------------------------------------------------
# run() — session-meta output (Step 3)
# ---------------------------------------------------------------------------


class TestRunSessionMetaOutput:
    def test_session_meta_written_to_output_dir(self, tmp_path: Path) -> None:
        session = _make_session("sess-abc")
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions([session]):
            result = run(days=30, skip_llm=True, all_workspaces=False, workspace=tmp_path)
        assert result == 0
        meta_path = tmp_path / ".copilot-insights" / "session-meta" / "sess-abc.json"
        assert meta_path.exists()

    def test_session_meta_contains_schema_version(self, tmp_path: Path) -> None:
        session = _make_session("sess-abc")
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions([session]):
            run(days=30, skip_llm=True, all_workspaces=False, workspace=tmp_path)
        meta_path = tmp_path / ".copilot-insights" / "session-meta" / "sess-abc.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION

    def test_multiple_sessions_produce_separate_meta_files(self, tmp_path: Path) -> None:
        sessions = [_make_session("sess-1"), _make_session("sess-2")]
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions(sessions):
            run(days=30, skip_llm=True, all_workspaces=False, workspace=tmp_path)
        meta_dir = tmp_path / ".copilot-insights" / "session-meta"
        assert (meta_dir / "sess-1.json").exists()
        assert (meta_dir / "sess-2.json").exists()


# ---------------------------------------------------------------------------
# run() — facets output (Step 4)
# ---------------------------------------------------------------------------


class TestRunFacetsOutput:
    def test_facets_written_when_llm_enabled(self, tmp_path: Path) -> None:
        session = _make_session("sess-abc")
        mock_llm = _make_mock_llm()
        with (
            _patch_resolve_workspace_ids(["ws-1"]),
            _patch_load_sessions([session]),
            patch("copilot_insights.__main__._init_llm_client", return_value=mock_llm),
        ):
            result = run(days=30, skip_llm=False, all_workspaces=False, workspace=tmp_path)
        assert result == 0
        facets_path = tmp_path / ".copilot-insights" / "facets" / "sess-abc.json"
        assert facets_path.exists()

    def test_facets_not_written_when_skip_llm(self, tmp_path: Path) -> None:
        session = _make_session("sess-abc")
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions([session]):
            run(days=30, skip_llm=True, all_workspaces=False, workspace=tmp_path)
        facets_dir = tmp_path / ".copilot-insights" / "facets"
        assert not facets_dir.exists()

    def test_existing_facets_not_overwritten(self, tmp_path: Path) -> None:
        session = _make_session("sess-abc")
        # Write a pre-existing facets file
        facets_dir = tmp_path / ".copilot-insights" / "facets"
        facets_dir.mkdir(parents=True)
        existing = facets_dir / "sess-abc.json"
        existing.write_text('{"existing": true}', encoding="utf-8")

        mock_llm = _make_mock_llm()
        with (
            _patch_resolve_workspace_ids(["ws-1"]),
            _patch_load_sessions([session]),
            patch("copilot_insights.__main__._init_llm_client", return_value=mock_llm),
        ):
            run(days=30, skip_llm=False, all_workspaces=False, workspace=tmp_path)

        # LLM should not have been called for the session that already has facets
        mock_llm.generate_facets_from_session.assert_not_called()
        # File content should be unchanged
        assert json.loads(existing.read_text(encoding="utf-8")) == {"existing": True}

    def test_facets_generation_error_does_not_abort_pipeline(self, tmp_path: Path) -> None:
        from copilot_insights.llm_client import FacetsGenerationError

        sessions = [_make_session("sess-1"), _make_session("sess-2")]
        mock_llm = MagicMock()
        # First session fails, second succeeds
        from copilot_insights.models import Facets

        mock_llm.generate_facets_from_session.side_effect = [
            FacetsGenerationError("bad response"),
            Facets(
                schema_version=SCHEMA_VERSION,
                session_id="sess-2",
                project_area="frontend",
                primary_goal="Build UI",
                session_type="feature_development",
                inferred_satisfaction="medium",
                wins=[],
                frictions=[],
                suggested_rules=[],
                suggested_patterns=[],
            ),
        ]
        with (
            _patch_resolve_workspace_ids(["ws-1"]),
            _patch_load_sessions(sessions),
            patch("copilot_insights.__main__._init_llm_client", return_value=mock_llm),
        ):
            result = run(days=30, skip_llm=False, all_workspaces=False, workspace=tmp_path)

        assert result == 0
        assert not (tmp_path / ".copilot-insights" / "facets" / "sess-1.json").exists()
        assert (tmp_path / ".copilot-insights" / "facets" / "sess-2.json").exists()

    def test_no_llm_call_when_api_key_missing(self, tmp_path: Path) -> None:
        session = _make_session("sess-abc")
        with (
            _patch_resolve_workspace_ids(["ws-1"]),
            _patch_load_sessions([session]),
            patch("copilot_insights.__main__._init_llm_client", return_value=None),
        ):
            result = run(days=30, skip_llm=False, all_workspaces=False, workspace=tmp_path)
        assert result == 0
        assert not (tmp_path / ".copilot-insights" / "facets").exists()


# ---------------------------------------------------------------------------
# run() — all-workspaces mode output location
# ---------------------------------------------------------------------------


class TestRunAllWorkspacesOutputDir:
    def test_output_written_to_cwd_when_all_workspaces(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        session = _make_session("sess-abc")
        with _patch_get_workspace_ids(["ws-1"]), _patch_load_sessions([session]):
            result = run(days=30, skip_llm=True, all_workspaces=True, workspace=None)
        assert result == 0
        assert (tmp_path / ".copilot-insights" / "session-meta" / "sess-abc.json").exists()
