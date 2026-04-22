# Writers for session-meta and facets JSON files under .copilot-insights/.
from __future__ import annotations

import json
from pathlib import Path

from copilot_insights.models import Facets, SessionMeta


def write_session_meta(output_dir: Path, meta: SessionMeta) -> Path:
    """Write a SessionMeta dict to ``output_dir/session-meta/{session_id}.json``.

    Creates intermediate directories if they do not exist.
    The JSON is written with 2-space indentation and a trailing newline.

    Args:
        output_dir: Root ``.copilot-insights/`` directory path.
        meta: Populated :class:`~copilot_insights.models.SessionMeta` dict.

    Returns:
        The :class:`~pathlib.Path` of the file that was written.
    """
    dest_dir = output_dir / "session-meta"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{meta['session_id']}.json"
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
    """
    dest_dir = output_dir / "facets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{facets['session_id']}.json"
    dest.write_text(json.dumps(facets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest
