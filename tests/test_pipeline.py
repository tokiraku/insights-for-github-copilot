# Integration tests for the full CLI pipeline (INFRA-002).
# Covers: run() orchestration — workspace resolution, session-meta extraction,
# and output file creation under .copilot-insights/.
# Facets generation is handled by the VS Code extension (vscode.lm API); not tested here.
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from copilot_insights.__main__ import run
from copilot_insights.models import SCHEMA_VERSION
from copilot_insights.parser import ParsedRequest, ParsedSession, ResponseChunk

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


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
# Helpers: mock load_sessions and workspace resolution
# ---------------------------------------------------------------------------


def _patch_load_sessions(sessions: list[ParsedSession]):
    return patch("copilot_insights.__main__.load_sessions", return_value=sessions)


def _patch_resolve_workspace_ids(ids: list[str]):
    return patch("copilot_insights.__main__.resolve_workspace_ids", return_value=ids)


def _patch_get_workspace_ids(ids: list[str]):
    return patch("copilot_insights.__main__.get_workspace_ids", return_value=ids)


# ---------------------------------------------------------------------------
# run() — --days validation
# ---------------------------------------------------------------------------


class TestRunDaysValidation:
    def test_returns_1_when_days_is_zero(self, tmp_path: Path) -> None:
        result = run(days=0, all_workspaces=False, workspace=tmp_path)
        assert result == 1

    def test_returns_1_when_days_is_negative(self, tmp_path: Path) -> None:
        result = run(days=-1, all_workspaces=False, workspace=tmp_path)
        assert result == 1

    def test_returns_success_when_days_is_one(self, tmp_path: Path) -> None:
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions([]):
            result = run(days=1, all_workspaces=False, workspace=tmp_path)
        assert result == 0


# ---------------------------------------------------------------------------
# run() — workspace resolution failures
# ---------------------------------------------------------------------------


class TestRunWorkspaceResolution:
    def test_returns_1_when_no_workspace_ids_found(self, tmp_path: Path) -> None:
        with _patch_resolve_workspace_ids([]):
            result = run(days=30, all_workspaces=False, workspace=tmp_path)
        assert result == 1

    def test_returns_1_when_all_workspaces_finds_nothing(self, tmp_path: Path) -> None:
        with _patch_get_workspace_ids([]), _patch_load_sessions([]):
            result = run(days=30, all_workspaces=True, workspace=None)
        assert result == 1

    def test_returns_0_when_no_sessions_in_period(self, tmp_path: Path) -> None:
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions([]):
            result = run(days=30, all_workspaces=False, workspace=tmp_path)
        assert result == 0


# ---------------------------------------------------------------------------
# run() — session-meta output (Step 3)
# ---------------------------------------------------------------------------


class TestRunSessionMetaOutput:
    def test_session_meta_written_to_output_dir(self, tmp_path: Path) -> None:
        session = _make_session("sess-abc")
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions([session]):
            result = run(days=30, all_workspaces=False, workspace=tmp_path)
        assert result == 0
        meta_path = tmp_path / ".copilot-insights" / "session-meta" / "sess-abc.json"
        assert meta_path.exists()

    def test_session_meta_contains_schema_version(self, tmp_path: Path) -> None:
        session = _make_session("sess-abc")
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions([session]):
            run(days=30, all_workspaces=False, workspace=tmp_path)
        meta_path = tmp_path / ".copilot-insights" / "session-meta" / "sess-abc.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION

    def test_multiple_sessions_produce_separate_meta_files(self, tmp_path: Path) -> None:
        sessions = [_make_session("sess-1"), _make_session("sess-2")]
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions(sessions):
            run(days=30, all_workspaces=False, workspace=tmp_path)
        meta_dir = tmp_path / ".copilot-insights" / "session-meta"
        assert (meta_dir / "sess-1.json").exists()
        assert (meta_dir / "sess-2.json").exists()

    def test_facets_dir_not_created_by_cli(self, tmp_path: Path) -> None:
        """CLI は facets を生成しない。facets/ ディレクトリは作成されないこと。"""
        session = _make_session("sess-abc")
        with _patch_resolve_workspace_ids(["ws-1"]), _patch_load_sessions([session]):
            run(days=30, all_workspaces=False, workspace=tmp_path)
        assert not (tmp_path / ".copilot-insights" / "facets").exists()


# ---------------------------------------------------------------------------
# run() — all-workspaces mode output location
# ---------------------------------------------------------------------------


class TestRunAllWorkspacesOutputDir:
    def test_output_written_to_cwd_when_all_workspaces(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        session = _make_session("sess-abc")
        with _patch_get_workspace_ids(["ws-1"]), _patch_load_sessions([session]):
            result = run(days=30, all_workspaces=True, workspace=None)
        assert result == 0
        assert (tmp_path / ".copilot-insights" / "session-meta" / "sess-abc.json").exists()
