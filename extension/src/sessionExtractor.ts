// Session-meta extractor: computes quantitative metadata from a ParsedSession.
// TypeScript port of src/copilot_insights/extractor.py.
import { SessionMeta } from "./models.js";
import { ParsedRequest, ParsedSession } from "./sessionParser.js";

const SCHEMA_VERSION = "1.0";

const EXT_TO_LANGUAGE: Record<string, string> = {
  py: "Python",
  ts: "TypeScript",
  tsx: "TypeScript",
  js: "JavaScript",
  jsx: "JavaScript",
  md: "Markdown",
  json: "JSON",
  yaml: "YAML",
  yml: "YAML",
  sh: "Shell",
  bash: "Shell",
  html: "HTML",
  css: "CSS",
  rs: "Rust",
  go: "Go",
  java: "Java",
  rb: "Ruby",
  php: "PHP",
  cs: "C#",
  cpp: "C++",
  c: "C",
  kt: "Kotlin",
  swift: "Swift",
  sql: "SQL",
  toml: "TOML",
  tf: "Terraform",
  dockerfile: "Dockerfile",
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Compute quantitative metadata from a parsed Copilot chat session.
 *
 * All fields are derived from the ParsedSession without accessing external resources.
 * Token counts are estimated from text lengths (1 token ≈ 4 characters).
 *
 * @param session - A fully parsed session produced by `parseJsonlFile`.
 * @returns A `SessionMeta` object populated with all required fields.
 */
export function extractSessionMeta(session: ParsedSession): SessionMeta {
  const { requests } = session;
  const invocations = extractToolInvocations(requests);

  const timestamps: Date[] = [];
  const messageHours: number[] = [];

  for (const req of requests) {
    const dt = parseTimestampMs(req.timestamp);
    if (dt !== null) {
      timestamps.push(dt);
      messageHours.push(dt.getUTCHours());
    }
  }

  const durationMinutes =
    timestamps.length >= 2
      ? (timestamps[timestamps.length - 1]!.getTime() - timestamps[0]!.getTime()) / 60000
      : 0;

  const userResponseTimes: number[] = [];
  for (let i = 1; i < timestamps.length; i++) {
    const delta = (timestamps[i]!.getTime() - timestamps[i - 1]!.getTime()) / 1000;
    userResponseTimes.push(Math.round(delta * 1000) / 1000);
  }

  const toolCounts = countTools(invocations);
  const toolErrors = countToolErrors(invocations);
  const { files: filesModified, languages } = extractFilesAndLanguages(invocations);
  const { added: linesAdded, removed: linesRemoved } = countDiffLines(invocations);
  const { inputTokens, outputTokens } = estimateTokens(requests);

  return {
    schema_version: SCHEMA_VERSION,
    session_id: session.sessionId,
    start_time: session.creationDate,
    duration_minutes: Math.round(durationMinutes * 100) / 100,
    user_message_count: requests.length,
    tool_counts: toolCounts,
    languages,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    lines_added: linesAdded,
    lines_removed: linesRemoved,
    files_modified: filesModified,
    tool_errors: toolErrors,
    user_response_times: userResponseTimes,
    message_hours: messageHours,
  };
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

type ToolInvocation = Record<string, unknown>;

/** Parse a request timestamp (Unix ms number) to a Date, or null on failure. */
function parseTimestampMs(ts: number): Date | null {
  if (!isFinite(ts) || ts === 0) {
    return null;
  }
  return new Date(ts);
}

/** Collect all parsed toolInvocationSerialized objects across all requests. */
function extractToolInvocations(requests: ParsedRequest[]): ToolInvocation[] {
  const invocations: ToolInvocation[] = [];
  for (const req of requests) {
    for (const chunk of req.responseChunks) {
      if (chunk.kind !== "toolInvocationSerialized") {
        continue;
      }
      // toolInvocationSerialized chunks store structured data directly in the chunk object,
      // not as a JSON-encoded string in the value field.
      // The value field typically contains display text; the actual tool data is in the chunk itself.
      // We treat the chunk as the invocation record.
      if (chunk.value) {
        try {
          const data = JSON.parse(chunk.value) as unknown;
          if (typeof data === "object" && data !== null) {
            invocations.push(data as ToolInvocation);
          }
        } catch {
          // value is not JSON — skip
        }
      }
    }
  }
  return invocations;
}

/** Return a mapping of tool name → invocation count. */
function countTools(invocations: ToolInvocation[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const inv of invocations) {
    const name = stringField(inv, "toolName", "name", "tool");
    if (name) {
      counts[name] = (counts[name] ?? 0) + 1;
    }
  }
  return counts;
}

/** Count invocations that ended with an error result. */
function countToolErrors(invocations: ToolInvocation[]): number {
  let errors = 0;
  for (const inv of invocations) {
    const result = inv["result"] ?? inv["output"] ?? "";
    if (typeof result === "string" && result.toLowerCase().startsWith("error")) {
      errors++;
    } else if (typeof result === "object" && result !== null && (result as Record<string, unknown>)["isError"]) {
      errors++;
    }
  }
  return errors;
}

/** Collect modified file paths and infer programming languages from extensions. */
function extractFilesAndLanguages(invocations: ToolInvocation[]): {
  files: string[];
  languages: string[];
} {
  const files: string[] = [];
  const langCounts: Record<string, number> = {};

  for (const inv of invocations) {
    const toolInput = resolveToolInput(inv);
    for (const key of ["file_path", "path", "filePath", "filename"] as const) {
      const pathVal = toolInput[key];
      if (typeof pathVal === "string" && pathVal) {
        if (!files.includes(pathVal)) {
          files.push(pathVal);
        }
        const ext = extractFileExtension(pathVal);
        if (ext) {
          const lang = EXT_TO_LANGUAGE[ext] ?? capitalize(ext);
          langCounts[lang] = (langCounts[lang] ?? 0) + 1;
        }
        break;
      }
    }
  }

  const languages = Object.keys(langCounts).sort(
    (a, b) => langCounts[b]! - langCounts[a]!,
  );
  return { files, languages };
}

/** Sum lines_added and lines_removed from tool invocation diffs. */
function countDiffLines(invocations: ToolInvocation[]): {
  added: number;
  removed: number;
} {
  let added = 0;
  let removed = 0;

  for (const inv of invocations) {
    const toolInput = resolveToolInput(inv);
    const toolName = stringField(inv, "toolName", "name").toLowerCase();

    if (toolName === "write" || toolName === "notebookedit" || toolName.includes("write")) {
      const content = stringField(toolInput, "content", "new_string");
      if (content) {
        added += countLines(content);
      }
    } else if (
      toolName === "edit" ||
      toolName === "str_replace" ||
      toolName === "str_replace_editor" ||
      toolName.includes("edit")
    ) {
      const newStr = stringField(toolInput, "new_string", "new_content");
      const oldStr = stringField(toolInput, "old_string", "old_content");
      if (newStr) added += countLines(newStr);
      if (oldStr) removed += countLines(oldStr);
    }

    const diff = stringField(toolInput, "diff");
    if (diff) {
      for (const line of diff.split("\n")) {
        if (line.startsWith("+") && !line.startsWith("+++")) added++;
        else if (line.startsWith("-") && !line.startsWith("---")) removed++;
      }
    }
  }

  return { added, removed };
}

/**
 * Estimate input/output token counts from message and response text lengths.
 * Uses 1 token ≈ 4 characters.
 */
function estimateTokens(requests: ParsedRequest[]): {
  inputTokens: number;
  outputTokens: number;
} {
  const inputChars = requests.reduce((sum, r) => sum + r.messageText.length, 0);
  const outputChars = requests.reduce((sum, r) => sum + r.responseText.length, 0);
  return {
    inputTokens: Math.max(1, Math.floor(inputChars / 4)),
    outputTokens: Math.max(1, Math.floor(outputChars / 4)),
  };
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/** Extract and parse the tool input object from an invocation record. */
function resolveToolInput(inv: ToolInvocation): Record<string, unknown> {
  const raw = inv["input"] ?? inv["parameters"] ?? inv["args"] ?? {};
  if (typeof raw === "object" && raw !== null) {
    return raw as Record<string, unknown>;
  }
  try {
    const parsed = JSON.parse(String(raw)) as unknown;
    if (typeof parsed === "object" && parsed !== null) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // ignore
  }
  return {};
}

/** Return the first non-empty string value found under the given keys. */
function stringField(obj: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const val = obj[key];
    if (typeof val === "string" && val) {
      return val;
    }
  }
  return "";
}

/** Return the lowercase file extension without the dot, or empty string. */
function extractFileExtension(filePath: string): string {
  const dotIdx = filePath.lastIndexOf(".");
  if (dotIdx === -1) return "";
  const ext = filePath.slice(dotIdx + 1).toLowerCase();
  return /^[a-z]+$/.test(ext) ? ext : "";
}

/** Count non-empty lines in a string. */
function countLines(text: string): number {
  const lines = text.split("\n").length;
  return text.endsWith("\n") ? lines - 1 : lines;
}

/** Capitalize the first letter of a string. */
function capitalize(s: string): string {
  return s.length === 0 ? s : s[0]!.toUpperCase() + s.slice(1);
}
