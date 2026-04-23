// TypeScript equivalents of the Python models in src/copilot_insights/models.py.
// These types describe the JSON files written to .copilot-insights/ by the CLI.

/** Quantitative metadata for a single Copilot Chat session (session-meta JSON). */
export interface SessionMeta {
  schema_version: string;
  session_id: string;
  start_time: string; // ISO 8601
  duration_minutes: number;
  user_message_count: number;
  tool_counts: Record<string, number>;
  languages: string[];
  input_tokens: number;
  output_tokens: number;
  lines_added: number;
  lines_removed: number;
  files_modified: string[];
  tool_errors: number;
  user_response_times: number[]; // seconds between user messages
  message_hours: number[]; // hour-of-day for each user message (0-23)
}

/** Qualitative LLM-generated analysis for a single session (facets JSON). */
export interface Facets {
  schema_version: string;
  session_id: string;
  project_area: string;
  primary_goal: string;
  session_type: string;
  inferred_satisfaction: string;
  wins: string[];
  frictions: string[];
  suggested_rules: string[];
  suggested_patterns: string[];
}

/**
 * Condensed representation of a session sent to vscode.lm for facets generation.
 * Contains only the quantitative fields needed for qualitative analysis (NFR-002).
 * Raw conversation text is never included.
 */
export interface SessionSummary {
  session_id: string;
  duration_minutes: number;
  user_message_count: number;
  tool_counts: Record<string, number>;
  languages: string[];
  input_tokens: number;
  output_tokens: number;
  lines_added: number;
  lines_removed: number;
  tool_errors: number;
}

/** Cross-session aggregated values used to render the summary and report. */
export interface AggregatedInsights {
  sessionCount: number;
  totalMessages: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalLinesAdded: number;
  totalLinesRemoved: number;
  /** Tool name → total invocation count across all sessions. */
  toolCounts: Record<string, number>;
  /** Language → session count that mentioned the language. */
  languageCounts: Record<string, number>;
  /** Project area → session count. */
  projectAreaCounts: Record<string, number>;
  /** Deduplicated win strings collected from all facets. */
  wins: string[];
  /** Deduplicated friction strings collected from all facets. */
  frictions: string[];
  /** Deduplicated suggested rules collected from all facets. */
  suggestedRules: string[];
}
