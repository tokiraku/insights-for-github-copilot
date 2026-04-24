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


def _read_workspace_json_folder(candidate_dir: Path) -> str | None:
    """Return the folder path stored in workspace.json, or None if absent.

    VS Code writes a ``workspace.json`` file containing a ``folder`` key
    (``file://`` URI) that identifies the workspace root.  This is the
    most reliable source for workspace path resolution.
    """
    wj = candidate_dir / "workspace.json"
    if not wj.exists():
        return None
    try:
        data = json.loads(wj.read_text(encoding="utf-8"))
        folder = data.get("folder")
        if isinstance(folder, str):
            return folder
    except (json.JSONDecodeError, OSError):
        pass
    return None


def find_workspace_ids(workspace_path: Path | None) -> list[str]:
    """Find all VS Code workspaceStorage IDs for the given workspace path.

    Searches each subdirectory for a ``workspace.json`` whose ``folder`` URI
    matches *workspace_path*.  Returns all matching IDs (a workspace can have
    multiple storage entries if it was opened multiple times).

    Args:
        workspace_path: Absolute path to the workspace root.  If None the
            function returns an empty list immediately.
    """
    if workspace_path is None:
        return []

    target = _normalize_path(workspace_path)
    storage_root = get_workspace_storage_root()

    if not storage_root.is_dir():
        return []

    matched: list[str] = []
    for candidate_dir in storage_root.iterdir():
        if not candidate_dir.is_dir():
            continue
        folder = _read_workspace_json_folder(candidate_dir)
        if folder and _normalize_path(_uri_to_path(folder)) == target:
            matched.append(candidate_dir.name)

    return matched


def find_workspace_id(workspace_path: Path | None) -> str | None:
    """Find the VS Code workspaceStorage ID for the given workspace path.

    Returns the first matching ID, or None if no match is found.
    Prefer :func:`find_workspace_ids` when multiple matches are possible.

    Args:
        workspace_path: Absolute path to the workspace root.  If None the
            function returns None immediately.
    """
    ids = find_workspace_ids(workspace_path)
    return ids[0] if ids else None


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

    Delegates to :func:`list_jsonl_files_with_ids` and returns paths only.
    Missing or empty directories are silently skipped.

    Args:
        workspace_ids: Ordered list of workspace ID strings to scan.

    Returns:
        List of Path objects, each pointing to a ``.jsonl`` session file.
    """
    return [path for _, path in list_jsonl_files_with_ids(workspace_ids)]


def list_jsonl_files_with_ids(workspace_ids: list[str]) -> list[tuple[str, Path]]:
    """Return (workspace_id, path) pairs for all .jsonl session files.

    Like :func:`list_jsonl_files` but also carries the workspace ID so that
    callers can associate each session with its originating workspace.

    Args:
        workspace_ids: Ordered list of workspace ID strings to scan.

    Returns:
        List of ``(workspace_id, path)`` tuples, sorted by path within each workspace.
    """
    result: list[tuple[str, Path]] = []
    for ws_id in workspace_ids:
        sessions_dir = get_chat_sessions_dir(ws_id)
        if not sessions_dir.is_dir():
            continue
        for path in sorted(sessions_dir.glob("*.jsonl")):
            result.append((ws_id, path))
    return result


def resolve_workspace_ids(workspace_path: Path | None) -> list[str]:
    """Return the list of workspace IDs to scan for chat sessions.

    When *workspace_path* is provided and matching IDs are found via
    ``workspace.json``, returns those IDs (a workspace may have multiple
    storage entries).  Otherwise falls back to all workspace IDs recognized by
    ``get_workspace_ids()``.

    Args:
        workspace_path: Absolute path to the current workspace root, or None.

    Returns:
        Ordered list of workspace ID strings.  Matched workspaces (if any)
        are always first.
    """
    matched_ids = find_workspace_ids(workspace_path)
    if matched_ids:
        return matched_ids

    return get_workspace_ids()
