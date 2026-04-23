# Unit tests for copilot_insights.workspace module.
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from copilot_insights.workspace import (
    _uri_to_path,
    find_workspace_id,
    get_chat_sessions_dir,
    get_workspace_ids,
    get_workspace_storage_root,
    list_jsonl_files,
    list_jsonl_files_with_ids,
    resolve_workspace_ids,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vscdb(db_path: Path, items: dict[str, str]) -> None:
    """Create a minimal state.vscdb with the given key→value pairs."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)"
        )
        for key, value in items.items():
            conn.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (key, value),
            )


# ---------------------------------------------------------------------------
# get_workspace_storage_root
# ---------------------------------------------------------------------------

class TestGetWorkspaceStorageRoot:
    def test_returns_path_under_appdata(self):
        with patch.dict("os.environ", {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"}):
            root = get_workspace_storage_root()
        assert root == Path("C:\\Users\\test\\AppData\\Roaming\\Code\\User\\workspaceStorage")

    def test_returns_path_type(self):
        root = get_workspace_storage_root()
        assert isinstance(root, Path)


# ---------------------------------------------------------------------------
# find_workspace_id
# ---------------------------------------------------------------------------

class TestFindWorkspaceId:
    def test_returns_none_when_workspace_path_is_none(self):
        assert find_workspace_id(None) is None

    def test_returns_none_when_storage_root_missing(self, tmp_path):
        missing = tmp_path / "nonexistent"
        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=missing,
        ):
            result = find_workspace_id(Path("/some/workspace"))
        assert result is None

    def test_finds_workspace_by_scm_repositories_key(self, tmp_path):
        ws_id = "abc123"
        target_folder = Path("C:/Users/test/myproject")

        workspace_dir = tmp_path / ws_id
        workspace_dir.mkdir()
        _make_vscdb(
            workspace_dir / "state.vscdb",
            {
                "scm:view:visibleRepositories": json.dumps(
                    [{"rootUri": str(target_folder)}]
                )
            },
        )

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = find_workspace_id(target_folder)

        assert result == ws_id

    def test_finds_workspace_by_terminal_layout_info(self, tmp_path):
        ws_id = "def456"
        target_folder = "/home/user/project"

        workspace_dir = tmp_path / ws_id
        workspace_dir.mkdir()
        _make_vscdb(
            workspace_dir / "state.vscdb",
            {
                "terminal.integrated.layoutInfo": json.dumps(
                    {"workspacePath": target_folder}
                )
            },
        )

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = find_workspace_id(Path(target_folder))

        assert result == ws_id

    def test_returns_none_when_no_match(self, tmp_path):
        ws_id = "ghi789"
        workspace_dir = tmp_path / ws_id
        workspace_dir.mkdir()
        _make_vscdb(
            workspace_dir / "state.vscdb",
            {"scm:view:visibleRepositories": json.dumps([{"rootUri": "/other/path"}])},
        )

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = find_workspace_id(Path("/completely/different"))

        assert result is None

    def test_skips_directory_without_vscdb(self, tmp_path):
        ws_id = "no_db"
        (tmp_path / ws_id).mkdir()  # no state.vscdb

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = find_workspace_id(Path("/some/path"))

        assert result is None

    def test_skips_corrupted_vscdb(self, tmp_path):
        ws_id = "corrupt"
        workspace_dir = tmp_path / ws_id
        workspace_dir.mkdir()
        db_path = workspace_dir / "state.vscdb"
        db_path.write_text("not a sqlite database")

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = find_workspace_id(Path("/some/path"))

        assert result is None


# ---------------------------------------------------------------------------
# get_workspace_ids
# ---------------------------------------------------------------------------

class TestGetWorkspaceIds:
    def test_returns_empty_list_when_storage_missing(self, tmp_path):
        missing = tmp_path / "nonexistent"
        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=missing,
        ):
            assert get_workspace_ids() == []

    def test_returns_ids_with_chat_sessions_dir(self, tmp_path):
        ws_id = "ws_with_sessions"
        ws_dir = tmp_path / ws_id
        (ws_dir / "chatSessions").mkdir(parents=True)

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            ids = get_workspace_ids()

        assert ws_id in ids

    def test_returns_ids_with_state_vscdb(self, tmp_path):
        ws_id = "ws_with_db"
        ws_dir = tmp_path / ws_id
        ws_dir.mkdir()
        (ws_dir / "state.vscdb").touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            ids = get_workspace_ids()

        assert ws_id in ids

    def test_excludes_files_at_root(self, tmp_path):
        (tmp_path / "some_file.txt").touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            ids = get_workspace_ids()

        assert "some_file.txt" not in ids

    def test_excludes_empty_directories(self, tmp_path):
        ws_id = "empty_dir"
        (tmp_path / ws_id).mkdir()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            ids = get_workspace_ids()

        assert ws_id not in ids


# ---------------------------------------------------------------------------
# resolve_workspace_ids
# ---------------------------------------------------------------------------

class TestResolveWorkspaceIds:
    def test_returns_matched_id_when_found(self, tmp_path):
        ws_id = "matched"
        target = Path("/my/project")
        ws_dir = tmp_path / ws_id
        ws_dir.mkdir()
        _make_vscdb(
            ws_dir / "state.vscdb",
            {"scm:view:visibleRepositories": json.dumps([{"rootUri": str(target)}])},
        )

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = resolve_workspace_ids(target)

        assert result == [ws_id]

    def test_falls_back_to_all_ids_when_no_match(self, tmp_path):
        ws_ids = ["ws1", "ws2"]
        for ws_id in ws_ids:
            ws_dir = tmp_path / ws_id
            (ws_dir / "chatSessions").mkdir(parents=True)

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = resolve_workspace_ids(Path("/no/match"))

        assert set(result) == set(ws_ids)

    def test_falls_back_when_workspace_path_is_none(self, tmp_path):
        ws_id = "ws_fallback"
        ws_dir = tmp_path / ws_id
        (ws_dir / "chatSessions").mkdir(parents=True)

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = resolve_workspace_ids(None)

        assert ws_id in result


# ---------------------------------------------------------------------------
# get_chat_sessions_dir
# ---------------------------------------------------------------------------

class TestGetChatSessionsDir:
    def test_returns_correct_path(self, tmp_path):
        ws_id = "abc123"
        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = get_chat_sessions_dir(ws_id)

        assert result == tmp_path / ws_id / "chatSessions"

    def test_returns_path_type(self, tmp_path):
        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = get_chat_sessions_dir("some_id")

        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# list_jsonl_files
# ---------------------------------------------------------------------------

class TestListJsonlFiles:
    def test_returns_jsonl_files_for_single_workspace(self, tmp_path):
        ws_id = "ws_a"
        sessions_dir = tmp_path / ws_id / "chatSessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "session1.jsonl").touch()
        (sessions_dir / "session2.jsonl").touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = list_jsonl_files([ws_id])

        assert len(result) == 2
        assert all(f.suffix == ".jsonl" for f in result)

    def test_aggregates_files_from_multiple_workspaces(self, tmp_path):
        for ws_id in ("ws1", "ws2"):
            sessions_dir = tmp_path / ws_id / "chatSessions"
            sessions_dir.mkdir(parents=True)
            (sessions_dir / f"{ws_id}_session.jsonl").touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = list_jsonl_files(["ws1", "ws2"])

        assert len(result) == 2

    def test_excludes_non_jsonl_files(self, tmp_path):
        ws_id = "ws_mixed"
        sessions_dir = tmp_path / ws_id / "chatSessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "session.jsonl").touch()
        (sessions_dir / "readme.txt").touch()
        (sessions_dir / "data.json").touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = list_jsonl_files([ws_id])

        assert len(result) == 1
        assert result[0].name == "session.jsonl"

    def test_returns_empty_list_when_chat_sessions_dir_missing(self, tmp_path):
        ws_id = "ws_no_sessions"
        (tmp_path / ws_id).mkdir()  # no chatSessions subdir

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = list_jsonl_files([ws_id])

        assert result == []

    def test_returns_empty_list_for_empty_workspace_list(self, tmp_path):
        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = list_jsonl_files([])

        assert result == []

    def test_skips_missing_workspace_id_silently(self, tmp_path):
        ws_id_valid = "ws_valid"
        sessions_dir = tmp_path / ws_id_valid / "chatSessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "session.jsonl").touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = list_jsonl_files(["nonexistent_ws", ws_id_valid])

        assert len(result) == 1

    def test_files_are_sorted_within_workspace(self, tmp_path):
        ws_id = "ws_sort"
        sessions_dir = tmp_path / ws_id / "chatSessions"
        sessions_dir.mkdir(parents=True)
        for name in ("c.jsonl", "a.jsonl", "b.jsonl"):
            (sessions_dir / name).touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = list_jsonl_files([ws_id])

        names = [f.name for f in result]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# _uri_to_path — file:// URI conversion
# ---------------------------------------------------------------------------

class TestUriToPath:
    def test_passthrough_plain_path(self):
        assert _uri_to_path("/home/user/project") == "/home/user/project"

    def test_passthrough_windows_path(self):
        assert _uri_to_path("C:\\Users\\test") == "C:\\Users\\test"

    def test_converts_file_uri_unix(self):
        result = _uri_to_path("file:///home/user/project")
        assert result == "/home/user/project"

    def test_converts_file_uri_windows(self):
        result = _uri_to_path("file:///C:/Users/test/myproject")
        assert result == "C:/Users/test/myproject"

    def test_decodes_percent_encoded_spaces(self):
        result = _uri_to_path("file:///home/user/my%20project")
        assert result == "/home/user/my project"

    def test_passthrough_non_file_scheme(self):
        uri = "https://example.com/repo"
        assert _uri_to_path(uri) == uri


class TestFindWorkspaceIdWithFileUri:
    def test_finds_workspace_by_file_uri_in_scm_key(self, tmp_path):
        ws_id = "uri_ws"
        target_folder = Path("/home/user/myproject")

        workspace_dir = tmp_path / ws_id
        workspace_dir.mkdir()
        _make_vscdb(
            workspace_dir / "state.vscdb",
            {
                "scm:view:visibleRepositories": json.dumps(
                    [{"rootUri": "file:///home/user/myproject"}]
                )
            },
        )

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = find_workspace_id(target_folder)

        assert result == ws_id

    def test_finds_workspace_by_percent_encoded_uri(self, tmp_path):
        ws_id = "encoded_ws"
        target_folder = Path("/home/user/my project")

        workspace_dir = tmp_path / ws_id
        workspace_dir.mkdir()
        _make_vscdb(
            workspace_dir / "state.vscdb",
            {
                "scm:view:visibleRepositories": json.dumps(
                    [{"rootUri": "file:///home/user/my%20project"}]
                )
            },
        )

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = find_workspace_id(target_folder)

        assert result == ws_id


# ---------------------------------------------------------------------------
# list_jsonl_files_with_ids
# ---------------------------------------------------------------------------

class TestListJsonlFilesWithIds:
    def test_returns_workspace_id_with_each_file(self, tmp_path):
        ws_id = "ws_a"
        sessions_dir = tmp_path / ws_id / "chatSessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "session1.jsonl").touch()
        (sessions_dir / "session2.jsonl").touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = list_jsonl_files_with_ids([ws_id])

        assert len(result) == 2
        assert all(ws == ws_id for ws, _ in result)
        assert all(p.suffix == ".jsonl" for _, p in result)

    def test_aggregates_from_multiple_workspaces_with_correct_ids(self, tmp_path):
        for ws_id in ("ws1", "ws2"):
            sessions_dir = tmp_path / ws_id / "chatSessions"
            sessions_dir.mkdir(parents=True)
            (sessions_dir / f"{ws_id}_session.jsonl").touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            result = list_jsonl_files_with_ids(["ws1", "ws2"])

        ws_ids_returned = {ws for ws, _ in result}
        assert ws_ids_returned == {"ws1", "ws2"}

    def test_list_jsonl_files_unchanged_behavior(self, tmp_path):
        """list_jsonl_files still returns just paths (no regression)."""
        ws_id = "ws_compat"
        sessions_dir = tmp_path / ws_id / "chatSessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "s.jsonl").touch()

        with patch(
            "copilot_insights.workspace.get_workspace_storage_root",
            return_value=tmp_path,
        ):
            paths = list_jsonl_files([ws_id])

        assert len(paths) == 1
        assert isinstance(paths[0], Path)
