# LLM API client for facets generation using Anthropic Claude.
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from copilot_insights.models import SCHEMA_VERSION, Facets, SessionMeta
from copilot_insights.parser import ParsedSession
from copilot_insights.summarizer import summarize_session

# Default model. Can be overridden by passing `model=` to AnthropicClient.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

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
  "session_type": "<one of: 'feature_development', 'bug_fixing', 'refactoring',
  'exploration', 'documentation', 'testing', 'configuration'>",
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


# Approximate USD cost per million tokens for claude-haiku-4-5 (prompt cache aware).
# Source: https://www.anthropic.com/pricing (2026-04).
_COST_PER_1M_INPUT = 0.80          # standard input tokens
_COST_PER_1M_CACHE_WRITE = 1.00    # cache write tokens
_COST_PER_1M_CACHE_READ = 0.08     # cache read tokens (90% discount)
_COST_PER_1M_OUTPUT = 4.00         # output tokens


class AnthropicClient:
    """Wrapper around the Anthropic SDK for generating session facets.

    Reads ANTHROPIC_API_KEY from the environment. Raises EnvironmentError
    if the key is absent. Uses prompt caching on the system prompt to
    reduce API costs when processing multiple sessions (NFR-005).

    Accumulates usage statistics across calls; call :meth:`log_usage_summary`
    after all sessions are processed to print cache hit rate and estimated cost.
    """

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
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

        # Accumulated token counts for NFR-005 cost tracking.
        self._total_input_tokens: int = 0
        self._total_cache_creation_tokens: int = 0
        self._total_cache_read_tokens: int = 0
        self._total_output_tokens: int = 0
        self._call_count: int = 0

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

        self._accumulate_usage(response)
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

    def _accumulate_usage(self, response: anthropic.types.Message) -> None:
        """Add token counts from a response to the running totals."""
        usage = response.usage
        self._total_input_tokens += _safe_token_count(usage, "input_tokens")
        self._total_cache_creation_tokens += _safe_token_count(usage, "cache_creation_input_tokens")
        self._total_cache_read_tokens += _safe_token_count(usage, "cache_read_input_tokens")
        self._total_output_tokens += _safe_token_count(usage, "output_tokens")
        self._call_count += 1

    def log_usage_summary(self) -> None:
        """Print accumulated token usage, cache hit rate, and estimated cost.

        Outputs to stdout so the summary appears in the normal pipeline run log.
        Does nothing if no API calls have been made.
        """
        if self._call_count == 0:
            return

        total_input = self._total_input_tokens + self._total_cache_creation_tokens + self._total_cache_read_tokens
        cache_hit_rate = (
            self._total_cache_read_tokens / total_input * 100 if total_input > 0 else 0.0
        )

        # Estimated cost in USD
        cost = (
            self._total_input_tokens * _COST_PER_1M_INPUT
            + self._total_cache_creation_tokens * _COST_PER_1M_CACHE_WRITE
            + self._total_cache_read_tokens * _COST_PER_1M_CACHE_READ
            + self._total_output_tokens * _COST_PER_1M_OUTPUT
        ) / 1_000_000

        print(
            f"\nLLM usage summary ({self._call_count} call(s)):\n"
            f"  Input tokens      : {self._total_input_tokens:,}\n"
            f"  Cache write tokens: {self._total_cache_creation_tokens:,}\n"
            f"  Cache read tokens : {self._total_cache_read_tokens:,}\n"
            f"  Output tokens     : {self._total_output_tokens:,}\n"
            f"  Cache hit rate    : {cache_hit_rate:.1f}%\n"
            f"  Estimated cost    : ${cost:.4f} USD"
            f" (based on claude-haiku-4-5 pricing; may differ for other models)"
        )


def _safe_token_count(usage: object, attr: str) -> int:
    """Return the integer token count from a usage object attribute, defaulting to 0."""
    return int(getattr(usage, attr, 0) or 0)


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

    list_fields = ("wins", "frictions", "suggested_rules", "suggested_patterns")
    for field in list_fields:
        value = data[field]
        if not isinstance(value, list):
            raise FacetsGenerationError(
                f"LLM response field '{field}' must be a list for session '{session_id}', "
                f"got {type(value).__name__}"
            )
        for i, item in enumerate(value):
            if not isinstance(item, str):
                raise FacetsGenerationError(
                    f"LLM response field '{field}[{i}]' must be a string for session '{session_id}', "
                    f"got {type(item).__name__}"
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
