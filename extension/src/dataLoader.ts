// Reads .copilot-insights/ intermediate data and aggregates it into a single
// AggregatedInsights object for use by the summary and report views.
import * as fs from "fs";
import * as path from "path";

import { AggregatedInsights, Facets, SessionMeta } from "./models.js";

const SESSION_META_DIR = "session-meta";
const FACETS_DIR = "facets";
const INSIGHTS_DIR = ".copilot-insights";

export class InsightsNotFoundError extends Error {
  constructor(insightsDir: string) {
    super(
      `No .copilot-insights/ data found at "${insightsDir}". ` +
        "Run `python -m copilot_insights` first to generate session metadata.",
    );
    this.name = "InsightsNotFoundError";
  }
}

/**
 * Load all SessionMeta objects from the `.copilot-insights/session-meta/` directory.
 *
 * @param workspaceRoot - Absolute path to the VS Code workspace root folder.
 * @returns Array of SessionMeta objects. Empty array when no files are found.
 * @throws {InsightsNotFoundError} When the `session-meta/` directory does not exist
 *   or contains no files (i.e. the CLI has not been run yet).
 */
export function loadSessionMetas(workspaceRoot: string): SessionMeta[] {
  const insightsDir = path.join(workspaceRoot, INSIGHTS_DIR);
  const metaDir = path.join(insightsDir, SESSION_META_DIR);

  if (!fs.existsSync(metaDir)) {
    throw new InsightsNotFoundError(insightsDir);
  }

  const sessionMetas = readJsonFiles<SessionMeta>(metaDir);
  if (sessionMetas.length === 0) {
    throw new InsightsNotFoundError(insightsDir);
  }

  return sessionMetas;
}

/**
 * Load and aggregate all session-meta and facets JSON files from the
 * `.copilot-insights/` directory located at the workspace root.
 *
 * Facets are optional — when the facets directory is absent or empty,
 * the aggregated result still contains all quantitative session-meta data.
 * Qualitative fields (wins, frictions, suggestedRules, projectAreaCounts)
 * will simply be empty until facets are generated via vscode.lm.
 *
 * @param workspaceRoot - Absolute path to the VS Code workspace root folder.
 * @returns Aggregated insights derived from all available session data.
 * @throws {InsightsNotFoundError} When the `.copilot-insights/` directory or
 *   its `session-meta/` sub-directory does not exist or contains no files.
 */
export function loadInsights(workspaceRoot: string): AggregatedInsights {
  const insightsDir = path.join(workspaceRoot, INSIGHTS_DIR);
  const metaDir = path.join(insightsDir, SESSION_META_DIR);
  const facetsDir = path.join(insightsDir, FACETS_DIR);

  const sessionMetas = loadSessionMetas(workspaceRoot);
  const facetsMap = buildFacetsMap(facetsDir);

  return aggregate(sessionMetas, facetsMap);
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Read all *.json files in a directory and parse them.
 * Files that fail to parse are silently skipped to avoid one corrupt file
 * breaking the entire load.
 */
function readJsonFiles<T>(dir: string): T[] {
  if (!fs.existsSync(dir)) {
    return [];
  }

  const results: T[] = [];
  for (const entry of fs.readdirSync(dir).sort()) {
    if (!entry.endsWith(".json")) {
      continue;
    }
    try {
      const raw = fs.readFileSync(path.join(dir, entry), "utf8");
      results.push(JSON.parse(raw) as T);
    } catch {
      // Skip malformed files without crashing.
    }
  }
  return results;
}

/** Build a session_id → Facets lookup from the facets directory. */
function buildFacetsMap(facetsDir: string): Map<string, Facets> {
  const map = new Map<string, Facets>();
  for (const facets of readJsonFiles<Facets>(facetsDir)) {
    if (facets.session_id) {
      map.set(facets.session_id, facets);
    }
  }
  return map;
}

/**
 * Aggregate raw session-meta and facets into a single summary object.
 *
 * String items (wins, frictions, suggested_rules) are deduplicated while
 * preserving first-seen order.
 */
function aggregate(
  metas: SessionMeta[],
  facetsMap: Map<string, Facets>,
): AggregatedInsights {
  const result: AggregatedInsights = {
    sessionCount: metas.length,
    totalMessages: 0,
    totalInputTokens: 0,
    totalOutputTokens: 0,
    totalLinesAdded: 0,
    totalLinesRemoved: 0,
    toolCounts: {},
    languageCounts: {},
    projectAreaCounts: {},
    wins: [],
    frictions: [],
    suggestedRules: [],
  };

  const seenWins = new Set<string>();
  const seenFrictions = new Set<string>();
  const seenRules = new Set<string>();

  for (const meta of metas) {
    result.totalMessages += meta.user_message_count;
    result.totalInputTokens += meta.input_tokens;
    result.totalOutputTokens += meta.output_tokens;
    result.totalLinesAdded += meta.lines_added;
    result.totalLinesRemoved += meta.lines_removed;

    for (const [tool, count] of Object.entries(meta.tool_counts)) {
      result.toolCounts[tool] = (result.toolCounts[tool] ?? 0) + count;
    }

    for (const lang of meta.languages) {
      result.languageCounts[lang] = (result.languageCounts[lang] ?? 0) + 1;
    }

    const facets = facetsMap.get(meta.session_id);
    if (!facets) {
      continue;
    }

    const area = facets.project_area;
    if (area) {
      result.projectAreaCounts[area] =
        (result.projectAreaCounts[area] ?? 0) + 1;
    }

    for (const win of facets.wins) {
      if (!seenWins.has(win)) {
        seenWins.add(win);
        result.wins.push(win);
      }
    }

    for (const friction of facets.frictions) {
      if (!seenFrictions.has(friction)) {
        seenFrictions.add(friction);
        result.frictions.push(friction);
      }
    }

    for (const rule of facets.suggested_rules) {
      if (!seenRules.has(rule)) {
        seenRules.add(rule);
        result.suggestedRules.push(rule);
      }
    }
  }

  return result;
}
