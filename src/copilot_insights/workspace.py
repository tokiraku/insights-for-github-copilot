# Workspace ID resolution for VS Code workspaceStorage.
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse


def get_workspace_storage_root() -> Path:
    """Return the path to VS Code's workspaceStorage directory."""
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(appdata) / "Code" / "User" / "workspaceStorage"


def _read_vscdb_value(db_path: Path, key: str) -> str | None:
    """Read a single value from a VS Code SQLite state.vscdb file."""
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else None
    except sqlite3.Error:
        return None


def _extract_folder_paths_from_vscdb(db_path: Path) -> list[str]:
    """Extract workspace folder paths stored in a state.vscdb file.

    Tries multiple known keys that VS Code uses to record open folder paths.
    Returns a list of normalized lowercase paths.
    """
    candidates: list[str] = []

    # scm:view:visibleRepositories — contains folder path(s) used for SCM
    raw = _read_vscdb_value(db_path, "scm:view:visibleRepositories")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        candidates.append(item.lower())
                    elif isinstance(item, dict):
                        for key in ("rootUri", "uri", "path", "fsPath"):
                            if key in item and isinstance(item[key], str):
                                candidates.append(item[key].lower())
                                break
        except (json.JSONDecodeError, TypeError):
            pass

    # terminal.integrated.layoutInfo — may embed workspaceId or folder path
    raw = _read_vscdb_value(db_path, "terminal.integrated.layoutInfo")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for key in ("workspaceId", "workspacePath", "folder"):
                    if key in data and isinstance(data[key], str):
                        candidates.append(data[key].lower())
        except (json.JSONDecodeError, TypeError):
            pass

    return candidates


def _uri_to_path(s: str) -> str:
    """Convert a file:// URI to a local filesystem path string.

    VS Code stores workspace paths as ``file:///C:/Users/...`` URIs in some
    state keys.  Passing such a string directly to ``Path()`` produces an
    incorrect result on Windows.  This helper extracts the path component and
    percent-decodes it so the caller can safely pass the result to ``Path()``.

    Non-URI strings are returned unchanged.
    """
    parsed = urlparse(s)
    if parsed.scheme == "file":
        path = unquote(parsed.path)
        # On Windows the path starts with /C:/...; strip the leading slash.
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return path
    return s


def _normalize_path(p: str | Path) -> str:
    """Return a normalized, lowercased string path for comparison.

    Handles ``file://`` URIs by converting them to local paths before
    resolving.
    """
    s = _uri_to_path(str(p)) if isinstance(p, str) else str(p)
    return str(Path(s).resolve()).lower()


def find_workspace_id(workspace_path: Path | None) -> str | None:
    """Find the VS Code workspaceStorage ID for the given workspace path.

    Searches each subdirectory of workspaceStorage for a state.vscdb whose
    stored paths match *workspace_path*.  Returns the matching ID string, or
    None if no match is found.

    Args:
        workspace_path: Absolute path to the workspace root.  If None the
            function returns None immediately.
    """
    if workspace_path is None:
        return None

    target = _normalize_path(workspace_path)
    storage_root = get_workspace_storage_root()

    if not storage_root.is_dir():
        return None

    for candidate_dir in storage_root.iterdir():
        if not candidate_dir.is_dir():
            continue
        db_path = candidate_dir / "state.vscdb"
        folder_paths = _extract_folder_paths_from_vscdb(db_path)
        for fp in folder_paths:
            if _normalize_path(fp) == target or fp == target:
                return candidate_dir.name

    return None


def get_workspace_ids() -> list[str]:
    """Return all workspace IDs found under VS Code's workspaceStorage.

    Each ID corresponds to one subdirectory that contains a chatSessions
    directory (or at least a state.vscdb).  Useful as a fallback when the
    current workspace cannot be identified.
    """
    storage_root = get_workspace_storage_root()
    if not storage_root.is_dir():
        return []

    ids: list[str] = []
    for candidate_dir in storage_root.iterdir():
        if not candidate_dir.is_dir():
            continue
        # Include directories that have chatSessions or state.vscdb
        has_sessions = (candidate_dir / "chatSessions").is_dir()
        has_db = (candidate_dir / "state.vscdb").exists()
        if has_sessions or has_db:
            ids.append(candidate_dir.name)

    return ids


def get_chat_sessions_dir(workspace_id: str) -> Path:
    """Return the chatSessions directory path for the given workspace ID.

    Args:
        workspace_id: The workspace storage directory name (hash string).
    """
    return get_workspace_storage_root() / workspace_id / "chatSessions"


def list_jsonl_files(workspace_ids: list[str]) -> list[Path]:
    """Return all .jsonl files found in the chatSessions dirs for the given IDs.

    Iterates each workspace ID in order and collects every ``*.jsonl`` file
    inside its ``chatSessions/`` directory.  Missing or empty directories are
    silently skipped.

    Args:
        workspace_ids: Ordered list of workspace ID strings to scan.

    Returns:
        List of Path objects, each pointing to a ``.jsonl`` session file.
    """
    files: list[Path] = []
    for ws_id in workspace_ids:
        sessions_dir = get_chat_sessions_dir(ws_id)
        if not sessions_dir.is_dir():
            continue
        files.extend(sorted(sessions_dir.glob("*.jsonl")))
    return files


def resolve_workspace_ids(workspace_path: Path | None) -> list[str]:
    """Return the list of workspace IDs to scan for chat sessions.

    When *workspace_path* is provided and a matching ID is found, returns a
    single-element list containing that ID.  Otherwise falls back to all
    workspace IDs recognized by ``get_workspace_ids()``, including those that
    contain a ``chatSessions`` directory or at least a ``state.vscdb`` file.

    Args:
        workspace_path: Absolute path to the current workspace root, or None.

    Returns:
        Ordered list of workspace ID strings.  The matched workspace (if any)
        is always first.
    """
    matched_id = find_workspace_id(workspace_path)
    if matched_id is not None:
        return [matched_id]

    return get_workspace_ids()
