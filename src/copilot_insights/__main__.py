"""CLI エントリポイント。python -m copilot_insights または copilot-insights コマンドで実行する。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from copilot_insights.extractor import extract_session_meta
from copilot_insights.session_loader import DEFAULT_DAYS, DEFAULT_MAX_SESSIONS, load_sessions
from copilot_insights.workspace import get_workspace_ids, resolve_workspace_ids
from copilot_insights.writer import write_session_meta


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the copilot-insights CLI."""
    parser = argparse.ArgumentParser(
        prog="copilot-insights",
        description="Analyze GitHub Copilot Chat session history and generate insights.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        metavar="N",
        help=f"Number of days to look back (default: {DEFAULT_DAYS})",
    )

    workspace_group = parser.add_mutually_exclusive_group()
    workspace_group.add_argument(
        "--all-workspaces",
        action="store_true",
        help="Scan all VS Code workspaces instead of the current one",
    )
    workspace_group.add_argument(
        "--workspace",
        type=Path,
        metavar="PATH",
        help="Path to the workspace root to analyze",
    )
    return parser


def run(
    days: int,
    all_workspaces: bool,
    workspace: Path | None,
) -> int:
    """Execute the copilot-insights pipeline.

    Orchestrates the FR-001 → FR-002 pipeline:
    1. Resolve workspace IDs
    2. Load and filter sessions
    3. Extract session-meta for each session and write to .copilot-insights/session-meta/

    Facets generation is handled by the VS Code extension via the vscode.lm API.

    Args:
        days: How many days back to include.
        all_workspaces: If True, scan every VS Code workspace.
        workspace: Explicit workspace root path, or None to auto-detect.

    Returns:
        Exit code (0 = success, non-zero = failure).
    """
    if days < 1:
        print("--days must be 1 or greater.", file=sys.stderr)
        return 1

    # Step 1: Resolve workspace IDs
    if all_workspaces:
        workspace_ids = get_workspace_ids()
        print(f"Scanning all workspaces ({len(workspace_ids)} found)...")
        output_root = Path.cwd() / ".copilot-insights"
    else:
        workspace_path = workspace or Path.cwd()
        workspace_ids = resolve_workspace_ids(workspace_path)
        if workspace_ids:
            print(f"Using workspace: {workspace_path}")
        else:
            print(f"No workspace storage found for: {workspace_path}", file=sys.stderr)
            print("Try --all-workspaces to scan all known workspaces.", file=sys.stderr)
            return 1
        output_root = workspace_path / ".copilot-insights"

    if not workspace_ids:
        print("No workspaces found. Is VS Code installed?", file=sys.stderr)
        return 1

    # Step 2: Load sessions
    print(f"Loading sessions (last {days} days, max {DEFAULT_MAX_SESSIONS})...")
    sessions = load_sessions(workspace_ids, days=days)
    if not sessions:
        print("No sessions found in the specified period.")
        return 0

    print(f"Found {len(sessions)} session(s).")

    # Step 3: session-meta extraction (FR-002)
    print("Extracting session metadata...")
    for i, session in enumerate(sessions, start=1):
        meta = extract_session_meta(session)
        write_session_meta(output_root, meta)
        print(f"  [{i}/{len(sessions)}] {meta['session_id'][:16]}... session-meta written")

    print(f"\nDone. Output written to: {output_root}")
    return 0


def main() -> None:
    """Parse CLI arguments and invoke run()."""
    parser = _build_parser()
    args = parser.parse_args()

    exit_code = run(
        days=args.days,
        all_workspaces=args.all_workspaces,
        workspace=args.workspace,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
