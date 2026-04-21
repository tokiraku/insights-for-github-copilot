# Session loading, filtering, and limiting logic for Copilot Chat JSONL files.
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from copilot_insights.parser import ParsedSession, parse_jsonl_file
from copilot_insights.workspace import list_jsonl_files

DEFAULT_DAYS = 30
DEFAULT_MAX_SESSIONS = 50


def _parse_creation_date(iso_str: str) -> datetime | None:
    """Parse an ISO 8601 creation_date string into an aware UTC datetime.

    Returns None if the string cannot be parsed.
    """
    if not iso_str:
        return None
    # Remove trailing 'Z' and add explicit UTC offset for fromisoformat
    normalized = iso_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def load_sessions(
    workspace_ids: list[str],
    days: int = DEFAULT_DAYS,
    max_sessions: int = DEFAULT_MAX_SESSIONS,
) -> list[ParsedSession]:
    """Load, filter, and limit Copilot Chat sessions from the given workspace IDs.

    Steps:
    1. Enumerate all ``.jsonl`` files for *workspace_ids* via
       :func:`~copilot_insights.workspace.list_jsonl_files`.
    2. Parse each file with :func:`~copilot_insights.parser.parse_jsonl_file`;
       skip files that cannot be parsed.
    3. Keep only sessions whose ``creation_date`` falls within the last *days*
       days (relative to now in UTC).  Sessions with an unparseable date are
       dropped.
    4. Sort the survivors newest-first and return at most *max_sessions* items.

    Args:
        workspace_ids: Ordered list of workspace ID strings to scan.
        days: How many days back to include (default 30).
        max_sessions: Maximum number of sessions to return (default 50).

    Returns:
        List of :class:`~copilot_insights.parser.ParsedSession` objects,
        newest-first, capped at *max_sessions*.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    jsonl_files: list[Path] = list_jsonl_files(workspace_ids)

    sessions: list[tuple[datetime, ParsedSession]] = []

    for path in jsonl_files:
        session = parse_jsonl_file(path)
        if session is None:
            continue

        created_at = _parse_creation_date(session["creation_date"])
        if created_at is None or created_at < cutoff:
            continue

        sessions.append((created_at, session))

    # Sort newest-first
    sessions.sort(key=lambda t: t[0], reverse=True)

    return [s for _, s in sessions[:max_sessions]]
