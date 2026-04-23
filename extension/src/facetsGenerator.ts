// Generates Facets JSON for each session using the vscode.lm API (Copilot).
// Raw conversation text is never sent; only quantitative session-meta is used (NFR-002).
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

import { Facets, SessionMeta, SessionSummary } from "./models.js";

const FACETS_DIR = ".copilot-insights/facets";
const SCHEMA_VERSION = "1.0";

// ---------------------------------------------------------------------------
// System prompt (equivalent to Python llm_client._SYSTEM_PROMPT)
// ---------------------------------------------------------------------------

const SYSTEM_PROMPT = `You are an expert analyst specializing in developer productivity and AI assistant usage patterns.
Your task is to analyze a GitHub Copilot chat session and produce a structured qualitative assessment.

You will receive session metadata (quantitative metrics only — no raw conversation text).

Return ONLY valid JSON matching this exact schema:
{
  "project_area": "<short phrase: e.g. 'backend API', 'frontend UI', 'infrastructure', 'testing'>",
  "primary_goal": "<one sentence describing the main objective of the session>",
  "session_type": "<one of: 'feature_development', 'bug_fixing', 'refactoring', 'exploration', 'documentation', 'testing', 'configuration'>",
  "inferred_satisfaction": "<one of: 'high', 'medium', 'low'>",
  "wins": ["<concrete achievement 1>", "<concrete achievement 2>"],
  "frictions": ["<obstacle or frustration 1>", "<obstacle or frustration 2>"],
  "suggested_rules": ["<rule to add to copilot-instructions.md>"],
  "suggested_patterns": ["<reusable pattern or workflow to adopt>"]
}

Rules:
- wins and frictions should each have 1-4 items; empty list if none observed
- suggested_rules and suggested_patterns should each have 0-3 items
- Do NOT include any explanation outside the JSON object`;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export class FacetsGenerationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FacetsGenerationError";
  }
}

/**
 * Generate facets for all sessions that don't yet have a facets JSON file.
 *
 * @param workspaceRoot - Absolute path to the workspace root.
 * @param metas         - Session metadata list to process.
 * @param token         - Cancellation token.
 * @param onProgress    - Optional callback invoked after each session is processed.
 */
export async function generateAllFacets(
  workspaceRoot: string,
  metas: SessionMeta[],
  token: vscode.CancellationToken,
  onProgress?: (current: number, total: number) => void,
): Promise<void> {
  const facetsDir = path.join(workspaceRoot, FACETS_DIR);
  fs.mkdirSync(facetsDir, { recursive: true });

  for (let i = 0; i < metas.length; i++) {
    if (token.isCancellationRequested) {
      break;
    }
    const meta = metas[i];
    const outPath = path.join(facetsDir, `${meta.session_id}.json`);
    if (fs.existsSync(outPath)) {
      onProgress?.(i + 1, metas.length);
      continue;
    }
    try {
      const facets = await generateFacets(meta, token);
      fs.writeFileSync(outPath, JSON.stringify(facets, null, 2), "utf8");
    } catch (err) {
      console.error(`[copilot-insights] Failed to generate facets for session ${meta.session_id}:`, err);
    }
    onProgress?.(i + 1, metas.length);
  }
}

/**
 * Generate a single Facets object for the given session metadata via vscode.lm.
 *
 * @param meta  - Quantitative session metadata.
 * @param token - Cancellation token.
 * @returns A populated Facets object.
 * @throws {FacetsGenerationError} When no Copilot model is available or the
 *   response cannot be parsed as valid Facets JSON.
 */
export async function generateFacets(
  meta: SessionMeta,
  token: vscode.CancellationToken,
): Promise<Facets> {
  const models = await vscode.lm.selectChatModels({ vendor: "copilot" });
  if (models.length === 0) {
    throw new FacetsGenerationError(
      "No Copilot language model is available. Ensure GitHub Copilot is enabled.",
    );
  }
  const model = models[0];

  const summary = buildSessionSummary(meta);
  const userContent = buildUserMessage(summary);

  const messages = [
    vscode.LanguageModelChatMessage.User(SYSTEM_PROMPT),
    vscode.LanguageModelChatMessage.User(userContent),
  ];

  const response = await model.sendRequest(messages, {}, token);

  let rawText = "";
  for await (const chunk of response.text) {
    rawText += chunk;
  }

  return parseFacets(rawText, meta.session_id);
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Extract only the fields needed for LLM analysis from a full SessionMeta. */
function buildSessionSummary(meta: SessionMeta): SessionSummary {
  return {
    session_id: meta.session_id,
    duration_minutes: meta.duration_minutes,
    user_message_count: meta.user_message_count,
    tool_counts: meta.tool_counts,
    languages: meta.languages,
    input_tokens: meta.input_tokens,
    output_tokens: meta.output_tokens,
    lines_added: meta.lines_added,
    lines_removed: meta.lines_removed,
    tool_errors: meta.tool_errors,
  };
}

/** Build the user message content from a SessionSummary. */
function buildUserMessage(summary: SessionSummary): string {
  return (
    "## Session Metadata\n" +
    "```json\n" +
    JSON.stringify(summary, null, 2) +
    "\n```"
  );
}

/**
 * Parse and validate the LLM's JSON output into a Facets object.
 *
 * @throws {FacetsGenerationError} On JSON decode failure or missing required keys.
 */
function parseFacets(rawText: string, sessionId: string): Facets {
  let text = rawText.trim();

  // Strip optional markdown code fences the model may add.
  if (text.startsWith("```")) {
    const lines = text.split("\n");
    const endIdx = lines.lastIndexOf("```");
    text = lines.slice(1, endIdx > 0 ? endIdx : lines.length).join("\n");
  }

  let data: Record<string, unknown>;
  try {
    data = JSON.parse(text) as Record<string, unknown>;
  } catch (e) {
    throw new FacetsGenerationError(
      `LLM response is not valid JSON for session '${sessionId}': ${String(e)}`,
    );
  }

  const requiredKeys = [
    "project_area",
    "primary_goal",
    "session_type",
    "inferred_satisfaction",
    "wins",
    "frictions",
    "suggested_rules",
    "suggested_patterns",
  ];
  const missing = requiredKeys.filter((k) => !(k in data));
  if (missing.length > 0) {
    throw new FacetsGenerationError(
      `LLM response missing required keys for session '${sessionId}': ${missing.join(", ")}`,
    );
  }

  const listFields = ["wins", "frictions", "suggested_rules", "suggested_patterns"] as const;
  for (const field of listFields) {
    if (!Array.isArray(data[field])) {
      throw new FacetsGenerationError(
        `LLM response field '${field}' must be an array for session '${sessionId}'`,
      );
    }
  }

  return {
    schema_version: SCHEMA_VERSION,
    session_id: sessionId,
    project_area: String(data["project_area"]),
    primary_goal: String(data["primary_goal"]),
    session_type: String(data["session_type"]),
    inferred_satisfaction: String(data["inferred_satisfaction"]),
    wins: (data["wins"] as unknown[]).map(String),
    frictions: (data["frictions"] as unknown[]).map(String),
    suggested_rules: (data["suggested_rules"] as unknown[]).map(String),
    suggested_patterns: (data["suggested_patterns"] as unknown[]).map(String),
  };
}
