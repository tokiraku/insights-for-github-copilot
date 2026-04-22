# Conversation summarizer: condenses a ParsedSession into a short text summary.
# The summary is sent to the LLM instead of the full chat text, keeping
# raw conversation data local (NFR-002).
from __future__ import annotations

from copilot_insights.parser import ParsedSession

# Maximum characters for the entire summary sent to the LLM.
_MAX_SUMMARY_CHARS = 1500

# Max characters per individual user message excerpt.
_MAX_MSG_CHARS = 200

# Max characters per assistant response excerpt.
_MAX_RESP_CHARS = 150


def summarize_session(session: ParsedSession) -> str:
    """Produce a concise text summary of a chat session for LLM input.

    Extracts only the first portion of each user message and assistant
    response.  The resulting summary is capped at ``_MAX_SUMMARY_CHARS``
    characters so that the full conversation text is never transmitted
    to the LLM API (NFR-002).

    Args:
        session: A fully parsed chat session.

    Returns:
        A plain-text summary string, at most ``_MAX_SUMMARY_CHARS`` chars.
        Returns an empty string if the session has no requests.
    """
    requests = session["requests"]
    if not requests:
        return ""

    lines: list[str] = []
    lines.append(f"Session: {session['session_id']}")
    lines.append(f"Model: {session['selected_model']}")
    lines.append(f"Messages: {len(requests)}")
    lines.append("")

    for i, req in enumerate(requests, start=1):
        msg = req["message_text"].strip()
        resp = req["response_text"].strip()

        msg_excerpt = _truncate(msg, _MAX_MSG_CHARS)
        resp_excerpt = _truncate(resp, _MAX_RESP_CHARS)

        lines.append(f"[{i}] User: {msg_excerpt}")
        if resp_excerpt:
            lines.append(f"    Assistant: {resp_excerpt}")

    summary = "\n".join(lines)
    return summary[:_MAX_SUMMARY_CHARS]


def _truncate(text: str, max_chars: int) -> str:
    """Return *text* truncated to *max_chars* with an ellipsis if cut."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"
