# LLM API client for facets generation using Anthropic Claude.
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from copilot_insights.models import SCHEMA_VERSION, Facets, SessionMeta
from copilot_insights.parser import ParsedSession
from copilot_insights.summarizer import summarize_session

# System prompt is defined once and eligible for prompt caching (NFR-005).
_SYSTEM_PROMPT = """You are an expert analyst specializing in developer productivity and AI assistant usage patterns.
Your task is to analyze a GitHub Copilot chat session and produce a structured qualitative assessment.

You will receive:
1. Session metadata (quantitative metrics)
2. A brief summary of the session's conversation (NOT the full conversation text)

Return ONLY valid JSON matching this exact schema:
{
  "project_area": "<short phrase: e.g. 'backend API', 'frontend UI', 'infrastructure', 'testing'>",
  "primary_goal": "<one sentence describing the main objective of the session>",
  "session_type": "<one of: 'feature_development', 'bug_fixing', 'refactoring', 'exploration',\
 'documentation', 'testing', 'configuration'>",
  "inferred_satisfaction": "<one of: 'high', 'medium', 'low'>",
  "wins": ["<concrete achievement 1>", "<concrete achievement 2>"],
  "frictions": ["<obstacle or frustration 1>", "<obstacle or frustration 2>"],
  "suggested_rules": ["<rule to add to copilot-instructions.md>"],
  "suggested_patterns": ["<reusable pattern or workflow to adopt>"]
}

Rules:
- wins and frictions should each have 1-4 items; empty list if none observed
- suggested_rules and suggested_patterns should each have 0-3 items
- All strings must be in the same language as the session conversation
- Do NOT include any explanation outside the JSON object"""


class FacetsGenerationError(Exception):
    """Raised when facets cannot be generated from the LLM response."""


class AnthropicClient:
    """Wrapper around the Anthropic SDK for generating session facets.

    Reads ANTHROPIC_API_KEY from the environment. Raises EnvironmentError
    if the key is absent. Uses prompt caching on the system prompt to
    reduce API costs when processing multiple sessions (NFR-005).
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        """Initialize the client, reading the API key from the environment.

        Args:
            model: Anthropic model ID to use for generation.

        Raises:
            EnvironmentError: If ANTHROPIC_API_KEY is not set.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise OSError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Set it before running copilot-insights."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate_facets(
        self,
        session_meta: SessionMeta,
        conversation_summary: str,
    ) -> Facets:
        """Generate qualitative facets for a session using the LLM.

        Sends session_meta and a brief conversation summary to the LLM.
        The full conversation text is NOT sent to comply with NFR-002
        (no raw chat data leaves the local machine).

        Args:
            session_meta: Quantitative metadata for the session.
            conversation_summary: A short human-readable summary of the
                session conversation (not the full text).

        Returns:
            A populated :class:`~copilot_insights.models.Facets` dict.

        Raises:
            FacetsGenerationError: If the LLM response cannot be parsed
                as a valid Facets object.
        """
        user_content = _build_user_message(session_meta, conversation_summary)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    # Cache the system prompt across calls within the same process
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = _extract_text(response)
        return _parse_facets(raw_text, session_meta["session_id"])

    def generate_facets_from_session(
        self,
        session: ParsedSession,
        session_meta: SessionMeta,
    ) -> Facets:
        """Generate facets from a ParsedSession, building the summary internally.

        Convenience wrapper that calls :func:`~copilot_insights.summarizer.summarize_session`
        to produce the conversation summary, then delegates to :meth:`generate_facets`.
        The full session text is never transmitted; only the truncated summary is sent.

        Args:
            session: The fully parsed chat session.
            session_meta: Pre-computed quantitative metadata for the session.

        Returns:
            A populated :class:`~copilot_insights.models.Facets` dict.
        """
        summary = summarize_session(session)
        return self.generate_facets(session_meta, summary)


def _build_user_message(meta: SessionMeta, summary: str) -> str:
    """Compose the user message from session_meta and conversation summary."""
    meta_excerpt: dict[str, Any] = {
        "session_id": meta["session_id"],
        "start_time": meta["start_time"],
        "duration_minutes": meta["duration_minutes"],
        "user_message_count": meta["user_message_count"],
        "tool_counts": meta["tool_counts"],
        "languages": meta["languages"],
        "input_tokens": meta["input_tokens"],
        "output_tokens": meta["output_tokens"],
        "lines_added": meta["lines_added"],
        "lines_removed": meta["lines_removed"],
        "files_modified": meta["files_modified"],
        "tool_errors": meta["tool_errors"],
    }
    return (
        "## Session Metadata\n"
        f"```json\n{json.dumps(meta_excerpt, ensure_ascii=False, indent=2)}\n```\n\n"
        "## Conversation Summary\n"
        f"{summary}"
    )


def _extract_text(response: anthropic.types.Message) -> str:
    """Pull the first text block from a Message response."""
    for block in response.content:
        if block.type == "text":
            return block.text
    raise FacetsGenerationError("LLM returned no text content in the response")


def _parse_facets(raw_text: str, session_id: str) -> Facets:
    """Parse and validate the LLM's JSON output into a Facets dict.

    Raises:
        FacetsGenerationError: On JSON decode failure or missing required keys.
    """
    # Strip optional markdown code fences the model may add
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FacetsGenerationError(
            f"LLM response is not valid JSON for session '{session_id}': {exc}"
        ) from exc

    required_keys = {
        "project_area",
        "primary_goal",
        "session_type",
        "inferred_satisfaction",
        "wins",
        "frictions",
        "suggested_rules",
        "suggested_patterns",
    }
    missing = required_keys - set(data.keys())
    if missing:
        raise FacetsGenerationError(
            f"LLM response missing required keys for session '{session_id}': {missing}"
        )

    return Facets(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        project_area=str(data["project_area"]),
        primary_goal=str(data["primary_goal"]),
        session_type=str(data["session_type"]),
        inferred_satisfaction=str(data["inferred_satisfaction"]),
        wins=list(data["wins"]),
        frictions=list(data["frictions"]),
        suggested_rules=list(data["suggested_rules"]),
        suggested_patterns=list(data["suggested_patterns"]),
    )
