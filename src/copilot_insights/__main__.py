"""CLI エントリポイント。python -m copilot_insights または copilot-insights コマンドで実行する。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from copilot_insights.extractor import extract_session_meta
from copilot_insights.llm_client import AnthropicClient, FacetsGenerationError
from copilot_insights.session_loader import DEFAULT_DAYS, DEFAULT_MAX_SESSIONS, load_sessions
from copilot_insights.workspace import get_workspace_ids, resolve_workspace_ids
from copilot_insights.writer import write_facets, write_session_meta


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
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM API calls; use existing facets JSON if available (NFR-006)",
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
    skip_llm: bool,
    all_workspaces: bool,
    workspace: Path | None,
) -> int:
    """Execute the copilot-insights pipeline.

    Orchestrates the full FR-001 → FR-002 → FR-003 pipeline:
    1. Resolve workspace IDs
    2. Load and filter sessions
    3. Extract session-meta for each session and write to .copilot-insights/session-meta/
    4. Generate facets via LLM and write to .copilot-insights/facets/ (unless --skip-llm)

    Args:
        days: How many days back to include.
        skip_llm: If True, skip LLM API calls.
        all_workspaces: If True, scan every VS Code workspace.
        workspace: Explicit workspace root path, or None to auto-detect.

    Returns:
        Exit code (0 = success, non-zero = failure).
    """
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
    metas = []
    for i, session in enumerate(sessions, start=1):
        meta = extract_session_meta(session)
        write_session_meta(output_root, meta)
        metas.append((session, meta))
        print(f"  [{i}/{len(sessions)}] {meta['session_id'][:16]}... session-meta written")

    # Step 4: facets generation (FR-003)
    if skip_llm:
        print("--skip-llm: LLM facets generation skipped.")
    else:
        llm_client = _init_llm_client()
        if llm_client is None:
            print("ANTHROPIC_API_KEY not set — skipping facets generation.", file=sys.stderr)
            print("Set ANTHROPIC_API_KEY or use --skip-llm to suppress this message.", file=sys.stderr)
        else:
            facets_dir = output_root / "facets"
            print("Generating facets via LLM...")
            for i, (session, meta) in enumerate(metas, start=1):
                session_id = meta["session_id"]
                existing_path = facets_dir / f"{session_id}.json"
                if existing_path.exists():
                    print(f"  [{i}/{len(metas)}] {session_id[:16]}... facets already exist, skipping")
                    continue
                try:
                    facets = llm_client.generate_facets_from_session(session, meta)
                    write_facets(output_root, facets)
                    print(f"  [{i}/{len(metas)}] {session_id[:16]}... facets written")
                except FacetsGenerationError as exc:
                    print(f"  [{i}/{len(metas)}] {session_id[:16]}... facets failed: {exc}", file=sys.stderr)

    print(f"\nDone. Output written to: {output_root}")
    return 0


def _init_llm_client() -> AnthropicClient | None:
    """Initialize the Anthropic LLM client, returning None if the API key is unset."""
    try:
        return AnthropicClient()
    except OSError:
        return None


def main() -> None:
    """Parse CLI arguments and invoke run()."""
    parser = _build_parser()
    args = parser.parse_args()

    exit_code = run(
        days=args.days,
        skip_llm=args.skip_llm,
        all_workspaces=args.all_workspaces,
        workspace=args.workspace,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
