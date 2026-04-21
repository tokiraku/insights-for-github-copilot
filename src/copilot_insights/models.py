# Type definitions for session-meta and facets intermediate data.
from __future__ import annotations

from typing import TypedDict

SCHEMA_VERSION = "1.0"


class ToolCounts(TypedDict):
    """Tool name → invocation count mapping."""

    name: str
    count: int


class SessionMeta(TypedDict):
    """Quantitative metadata extracted from a single Copilot chat session."""

    schema_version: str
    session_id: str
    start_time: str  # ISO 8601
    duration_minutes: float
    user_message_count: int
    tool_counts: dict[str, int]
    languages: list[str]
    input_tokens: int
    output_tokens: int
    lines_added: int
    lines_removed: int
    files_modified: list[str]
    tool_errors: int
    user_response_times: list[float]  # seconds between user messages
    message_hours: list[int]  # hour-of-day for each user message (0-23)


class Facets(TypedDict):
    """Qualitative analysis of a session produced by LLM."""

    schema_version: str
    session_id: str
    project_area: str
    primary_goal: str
    session_type: str
    inferred_satisfaction: str
    wins: list[str]
    frictions: list[str]
    suggested_rules: list[str]
    suggested_patterns: list[str]
