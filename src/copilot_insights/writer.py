# Writers for session-meta and facets JSON files under .copilot-insights/.
from __future__ import annotations

import json
import re
from pathlib import Path

from copilot_insights.models import Facets, SessionMeta

# Allow only alphanumerics, hyphens, and underscores in session_id filenames.
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9\-_]")


def _safe_filename(session_id: str, dest_dir: Path) -> Path:
    """Return a sanitized output path for *session_id* under *dest_dir*.

    Strips characters that could introduce path traversal (slashes, dots, etc.)
    and verifies the resolved path stays within *dest_dir*.

    Raises:
        ValueError: If the sanitized id is empty or the resolved path escapes
            *dest_dir* after sanitization.
    """
    sanitized = _SAFE_ID_RE.sub("", session_id)
    if not sanitized:
        raise ValueError(f"session_id '{session_id}' contains no safe characters")
    dest = dest_dir / f"{sanitized}.json"
    # Guard: resolved path must be a direct child of dest_dir
    if dest.resolve().parent != dest_dir.resolve():
        raise ValueError(f"Resolved path '{dest}' escapes output directory '{dest_dir}'")
    return dest


def write_session_meta(output_dir: Path, meta: SessionMeta) -> Path:
    """Write a SessionMeta dict to ``output_dir/session-meta/{session_id}.json``.

    Creates intermediate directories if they do not exist.
    The JSON is written with 2-space indentation and a trailing newline.

    Args:
        output_dir: Root ``.copilot-insights/`` directory path.
        meta: Populated :class:`~copilot_insights.models.SessionMeta` dict.

    Returns:
        The :class:`~pathlib.Path` of the file that was written.

    Raises:
        ValueError: If ``session_id`` cannot be safely used as a filename.
    """
    dest_dir = output_dir / "session-meta"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _safe_filename(meta["session_id"], dest_dir)
    dest.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def write_facets(output_dir: Path, facets: Facets) -> Path:
    """Write a Facets dict to ``output_dir/facets/{session_id}.json``.

    Creates intermediate directories if they do not exist.

    Args:
        output_dir: Root ``.copilot-insights/`` directory path.
        facets: Populated :class:`~copilot_insights.models.Facets` dict.

    Returns:
        The :class:`~pathlib.Path` of the file that was written.

    Raises:
        ValueError: If ``session_id`` cannot be safely used as a filename.
    """
    dest_dir = output_dir / "facets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _safe_filename(facets["session_id"], dest_dir)
    dest.write_text(json.dumps(facets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest
