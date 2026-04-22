# Session-meta extractor: computes quantitative metadata from a ParsedSession.
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from copilot_insights.models import SCHEMA_VERSION, SessionMeta
from copilot_insights.parser import ParsedRequest, ParsedSession


def _parse_timestamp_ms(raw: str | float | int) -> datetime | None:
    """Parse a request timestamp (Unix ms or ISO 8601) into an aware UTC datetime."""
    if not raw and raw != 0:
        return None
    try:
        ms = float(raw)
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    except (TypeError, ValueError):
        pass
    # Fallback: try ISO 8601 string
    if isinstance(raw, str):
        normalized = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            pass
    return None


def _extract_tool_invocations(requests: list[ParsedRequest]) -> list[dict[str, Any]]:
    """Collect all parsed toolInvocationSerialized objects across all requests."""
    invocations: list[dict[str, Any]] = []
    for req in requests:
        for chunk in req["response_chunks"]:
            if chunk["kind"] != "toolInvocationSerialized":
                continue
            try:
                data = json.loads(chunk["value"])
                if isinstance(data, dict):
                    invocations.append(data)
            except (json.JSONDecodeError, TypeError):
                continue
    return invocations


def _count_tools(invocations: list[dict[str, Any]]) -> dict[str, int]:
    """Return a mapping of tool name → invocation count."""
    counts: dict[str, int] = {}
    for inv in invocations:
        name = inv.get("toolName") or inv.get("name") or inv.get("tool") or ""
        if isinstance(name, str) and name:
            counts[name] = counts.get(name, 0) + 1
    return counts


def _count_tool_errors(invocations: list[dict[str, Any]]) -> int:
    """Count invocations that ended with an error result."""
    errors = 0
    for inv in invocations:
        result = inv.get("result") or inv.get("output") or ""
        if isinstance(result, str) and result.lower().startswith("error"):
            errors += 1
        elif isinstance(result, dict) and result.get("isError"):
            errors += 1
    return errors


def _extract_file_extension(path: str) -> str | None:
    """Return the lowercase extension of a file path, without the dot."""
    if "." in path:
        ext = path.rsplit(".", 1)[-1].lower()
        if ext and ext.isalpha():
            return ext
    return None


_EXT_TO_LANGUAGE: dict[str, str] = {
    "py": "Python",
    "ts": "TypeScript",
    "tsx": "TypeScript",
    "js": "JavaScript",
    "jsx": "JavaScript",
    "md": "Markdown",
    "json": "JSON",
    "yaml": "YAML",
    "yml": "YAML",
    "sh": "Shell",
    "bash": "Shell",
    "html": "HTML",
    "css": "CSS",
    "rs": "Rust",
    "go": "Go",
    "java": "Java",
    "rb": "Ruby",
    "php": "PHP",
    "cs": "C#",
    "cpp": "C++",
    "c": "C",
    "kt": "Kotlin",
    "swift": "Swift",
    "sql": "SQL",
    "toml": "TOML",
    "tf": "Terraform",
    "dockerfile": "Dockerfile",
}


def _extract_files_and_languages(
    invocations: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Collect modified file paths and infer programming languages from extensions."""
    files: list[str] = []
    lang_counts: dict[str, int] = {}

    for inv in invocations:
        # Tool input may carry a file path under various keys
        tool_input = inv.get("input") or inv.get("parameters") or inv.get("args") or {}
        if not isinstance(tool_input, dict):
            try:
                tool_input = json.loads(str(tool_input))
            except (json.JSONDecodeError, TypeError):
                tool_input = {}

        for key in ("file_path", "path", "filePath", "filename"):
            path_val = tool_input.get(key)
            if isinstance(path_val, str) and path_val:
                if path_val not in files:
                    files.append(path_val)
                ext = _extract_file_extension(path_val)
                if ext:
                    lang = _EXT_TO_LANGUAGE.get(ext, ext.capitalize())
                    lang_counts[lang] = lang_counts.get(lang, 0) + 1
                break

    # Return languages sorted by frequency (descending)
    languages = sorted(lang_counts, key=lambda k: lang_counts[k], reverse=True)
    return files, languages


def _count_diff_lines(
    invocations: list[dict[str, Any]],
) -> tuple[int, int]:
    """Sum lines_added and lines_removed from tool invocation diffs.

    Looks for unified-diff style content (``+`` / ``-`` prefixed lines) in
    tool input fields such as ``new_string``, ``content``, ``diff``, etc.
    """
    added = 0
    removed = 0

    for inv in invocations:
        tool_input = inv.get("input") or inv.get("parameters") or inv.get("args") or {}
        if not isinstance(tool_input, dict):
            try:
                tool_input = json.loads(str(tool_input))
            except (json.JSONDecodeError, TypeError):
                tool_input = {}

        # Write / create tool: count new lines as additions
        tool_name = (inv.get("toolName") or inv.get("name") or "").lower()
        if tool_name in ("write", "notebookedit") or "write" in tool_name:
            content = tool_input.get("content") or tool_input.get("new_string") or ""
            if isinstance(content, str):
                added += content.count("\n") + (1 if content and not content.endswith("\n") else 0)

        # Edit tool: new_string lines are added, old_string lines are removed
        elif tool_name in ("edit", "str_replace", "str_replace_editor") or "edit" in tool_name:
            new_str = tool_input.get("new_string") or tool_input.get("new_content") or ""
            old_str = tool_input.get("old_string") or tool_input.get("old_content") or ""
            if isinstance(new_str, str):
                added += new_str.count("\n") + (1 if new_str and not new_str.endswith("\n") else 0)
            if isinstance(old_str, str):
                removed += old_str.count("\n") + (1 if old_str and not old_str.endswith("\n") else 0)

        # Generic diff field
        diff = tool_input.get("diff") or ""
        if isinstance(diff, str):
            for line in diff.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    added += 1
                elif line.startswith("-") and not line.startswith("---"):
                    removed += 1

    return added, removed


def _estimate_tokens(requests: list[ParsedRequest]) -> tuple[int, int]:
    """Estimate input/output token counts from message and response text lengths.

    Uses the rough approximation of 1 token ≈ 4 characters.
    This is a best-effort estimate; actual token counts are not stored in JSONL.
    """
    input_chars = sum(len(r["message_text"]) for r in requests)
    output_chars = sum(len(r["response_text"]) for r in requests)
    return max(1, input_chars // 4), max(1, output_chars // 4)


def extract_session_meta(session: ParsedSession) -> SessionMeta:
    """Compute quantitative metadata from a parsed Copilot chat session.

    Derives all SessionMeta fields from the ParsedSession without accessing
    any external resources.  Token counts are estimated from text lengths.

    Args:
        session: A fully parsed session produced by
            :func:`~copilot_insights.parser.parse_jsonl_file`.

    Returns:
        A :class:`~copilot_insights.models.SessionMeta` dict populated with
        all required fields.
    """
    requests = session["requests"]
    invocations = _extract_tool_invocations(requests)

    # Timestamps for duration and response-time calculations
    timestamps: list[datetime] = []
    message_hours: list[int] = []
    for req in requests:
        dt = _parse_timestamp_ms(req["timestamp"])
        if dt is not None:
            timestamps.append(dt)
            message_hours.append(dt.hour)

    # Duration: difference between first and last request timestamp
    if len(timestamps) >= 2:
        duration_minutes = (timestamps[-1] - timestamps[0]).total_seconds() / 60.0
    else:
        duration_minutes = 0.0

    # User response times: seconds between consecutive messages
    user_response_times: list[float] = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        user_response_times.append(round(delta, 3))

    # Start time: creation_date from session init (ISO 8601 string)
    start_time = session["creation_date"]

    tool_counts = _count_tools(invocations)
    tool_errors = _count_tool_errors(invocations)
    files_modified, languages = _extract_files_and_languages(invocations)
    lines_added, lines_removed = _count_diff_lines(invocations)
    input_tokens, output_tokens = _estimate_tokens(requests)

    return SessionMeta(
        schema_version=SCHEMA_VERSION,
        session_id=session["session_id"],
        start_time=start_time,
        duration_minutes=round(duration_minutes, 2),
        user_message_count=len(requests),
        tool_counts=tool_counts,
        languages=languages,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        lines_added=lines_added,
        lines_removed=lines_removed,
        files_modified=files_modified,
        tool_errors=tool_errors,
        user_response_times=user_response_times,
        message_hours=message_hours,
    )
