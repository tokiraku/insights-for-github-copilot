# JSONL parser for VS Code Copilot Chat session files.
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict


class ResponseChunk(TypedDict):
    """A single element from a request's response array."""

    value: str
    kind: str  # "markdownContent", "thinking", "toolInvocationSerialized", etc.
                # Empty string when the key is absent (plain markdown answer).


class ParsedRequest(TypedDict):
    """One user→assistant exchange within a session."""

    request_id: str
    timestamp: str  # ISO 8601 string as stored in the JSONL
    agent: str
    model_id: str
    message_text: str
    response_text: str  # Concatenated markdown answer chunks
    response_chunks: list[ResponseChunk]
    time_spent_waiting: float  # milliseconds (unit as stored; may be ms or s)


class ParsedSession(TypedDict):
    """Parsed representation of a single `.jsonl` session file."""

    session_id: str
    creation_date: str  # ISO 8601 string
    selected_model: str
    requests: list[ParsedRequest]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_creation_date(raw: Any) -> str:
    """Normalize a creationDate value to an ISO 8601 string.

    VS Code may store creationDate as either an ISO 8601 string or a Unix
    timestamp in milliseconds (int/float).  Always returns a string so that
    downstream consumers (SessionMeta.start_time, etc.) receive a consistent type.
    """
    if isinstance(raw, (int, float)) and (raw or raw == 0):
        try:
            return datetime.fromtimestamp(raw / 1000.0, tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            return str(raw)
    return str(raw) if raw is not None else ""


def _extract_markdown_text(response: list[Any]) -> str:
    """Concatenate all markdown answer chunks from a response array.

    Markdown answer chunks are objects that have a ``value`` field and either
    no ``kind`` key or ``kind == "markdownContent"``.
    """
    parts: list[str] = []
    for chunk in response:
        if not isinstance(chunk, dict):
            continue
        kind = chunk.get("kind")
        value = chunk.get("value")
        if isinstance(value, str) and (kind is None or kind == "markdownContent"):
            parts.append(value)
    return "".join(parts)


def _normalize_response_chunks(response: list[Any]) -> list[ResponseChunk]:
    """Convert raw response array items into typed ResponseChunk dicts."""
    chunks: list[ResponseChunk] = []
    for item in response:
        if not isinstance(item, dict):
            continue
        value = item.get("value", "")
        raw_kind = item.get("kind", "")
        # Guard against non-string kind values (e.g. null in JSON)
        kind: str = raw_kind if isinstance(raw_kind, str) else ""
        if isinstance(value, str):
            chunks.append(ResponseChunk(value=value, kind=kind))
    return chunks


def _build_request(raw: dict[str, Any]) -> ParsedRequest:
    """Convert a raw request dict (from a kind=2 snapshot) to ParsedRequest."""
    response_raw: list[Any] = raw.get("response") or []
    message = raw.get("message")
    message_text = message.get("text", "") if isinstance(message, dict) else ""
    raw_wait = raw.get("timeSpentWaiting", 0.0)
    try:
        time_spent_waiting = float(raw_wait)
    except (TypeError, ValueError):
        time_spent_waiting = 0.0
    return ParsedRequest(
        request_id=raw.get("requestId", ""),
        timestamp=raw.get("timestamp", ""),
        agent=raw.get("agent", ""),
        model_id=raw.get("modelId", ""),
        message_text=message_text,
        response_text=_extract_markdown_text(response_raw),
        response_chunks=_normalize_response_chunks(response_raw),
        time_spent_waiting=time_spent_waiting,
    )


def _apply_response_patch(
    requests: list[dict[str, Any]],
    patch_index: int,
    patch_response: list[Any],
) -> None:
    """Merge a kind=2 response-patch into the corresponding request in-place.

    ``k=["requests", N, "response"]`` lines carry incremental response chunks.
    We append the new chunks to the existing response list rather than
    replacing it, because each patch line only contains the delta since the
    previous write.
    """
    if patch_index >= len(requests):
        return
    existing = requests[patch_index].get("response") or []
    requests[patch_index]["response"] = existing + patch_response


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_jsonl_file(path: Path) -> ParsedSession | None:
    """Parse a single Copilot Chat session `.jsonl` file.

    Reads every line and processes:
    - ``kind=0``: session initialisation (session_id, creation_date, model).
    - ``kind=2, k=["requests"]``: full request snapshot; last occurrence wins.
    - ``kind=2, k=["requests", N, "response"]``: incremental response patch
      applied on top of the most recent snapshot.

    Returns a :class:`ParsedSession` on success, or ``None`` if the file
    cannot be read or does not contain a valid kind=0 line.

    Args:
        path: Absolute path to the ``.jsonl`` file.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    session_id = ""
    creation_date = ""
    selected_model = ""
    found_init = False

    # Raw request list from the last k=["requests"] snapshot
    snapshot_requests: list[dict[str, Any]] = []
    # Response patches collected after the last snapshot: index → chunks
    response_patches: dict[int, list[Any]] = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        kind = record.get("kind")

        if kind == 0:
            v = record.get("v") or {}
            session_id = v.get("sessionId", "")
            creation_date = _normalize_creation_date(v.get("creationDate", ""))
            selected_model = v.get("selectedModel", "")
            found_init = True

        elif kind == 2:
            k = record.get("k")
            v = record.get("v")

            if k == ["requests"] and isinstance(v, list):
                # Full snapshot — reset accumulated state
                snapshot_requests = [r for r in v if isinstance(r, dict)]
                response_patches = {}

            elif (
                isinstance(k, list)
                and len(k) == 3
                and k[0] == "requests"
                and k[2] == "response"
                and isinstance(k[1], int)
                and isinstance(v, list)
            ):
                # Incremental response patch for request at index k[1]
                idx: int = k[1]
                existing = response_patches.get(idx, [])
                response_patches[idx] = existing + v

    if not found_init:
        return None

    # Apply collected response patches to the snapshot
    for idx, chunks in response_patches.items():
        _apply_response_patch(snapshot_requests, idx, chunks)

    requests = [_build_request(r) for r in snapshot_requests]

    return ParsedSession(
        session_id=session_id,
        creation_date=creation_date,
        selected_model=selected_model,
        requests=requests,
    )
