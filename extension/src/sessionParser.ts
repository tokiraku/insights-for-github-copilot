// JSONL parser for VS Code Copilot Chat session files.
// TypeScript port of src/copilot_insights/parser.py.
import * as fs from "fs";

/** A single element from a request's response array. */
export interface ResponseChunk {
  value: string;
  /** "markdownContent", "thinking", "toolInvocationSerialized", etc. Empty string when absent. */
  kind: string;
}

/** One user→assistant exchange within a session. */
export interface ParsedRequest {
  requestId: string;
  /** Unix timestamp in milliseconds. */
  timestamp: number;
  modelId: string;
  messageText: string;
  /** Concatenated markdown answer chunks. */
  responseText: string;
  responseChunks: ResponseChunk[];
  /** Raw time-spent-waiting value as stored in the JSONL (unit may vary). */
  timeSpentWaiting: number;
}

/** Parsed representation of a single `.jsonl` session file. */
export interface ParsedSession {
  sessionId: string;
  /** ISO 8601 string. */
  creationDate: string;
  selectedModel: string;
  requests: ParsedRequest[];
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Parse a single Copilot Chat session `.jsonl` file.
 *
 * Processes:
 * - `kind=0`: session initialisation (sessionId, creationDate, model).
 * - `kind=2, k=["requests"]`: full request snapshot; last occurrence wins.
 * - `kind=2, k=["requests", N, "response"]`: incremental response patch.
 *
 * @param filePath - Absolute path to the `.jsonl` file.
 * @returns Parsed session, or `null` if the file cannot be read or has no valid kind=0 line.
 */
export function parseJsonlFile(filePath: string): ParsedSession | null {
  let raw: string;
  try {
    raw = fs.readFileSync(filePath, "utf8");
  } catch {
    return null;
  }

  const lines = raw.split(/\r?\n/);

  let sessionId = "";
  let creationDate = "";
  let selectedModel = "";
  let foundInit = false;

  // Raw request list from the last k=["requests"] snapshot.
  let snapshotRequests: RawRequest[] = [];
  // Response patches collected after the last snapshot: index → chunks.
  const responsePatches = new Map<number, RawResponseItem[]>();

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }

    let record: Record<string, unknown>;
    try {
      record = JSON.parse(trimmed) as Record<string, unknown>;
    } catch {
      continue;
    }

    const kind = record["kind"];

    if (kind === 0) {
      const v = (record["v"] ?? {}) as Record<string, unknown>;
      sessionId = String(v["sessionId"] ?? "");
      creationDate = normalizeCreationDate(v["creationDate"]);
      // selectedModel may be a string identifier or a nested object — take string form.
      const sm = v["selectedModel"];
      selectedModel = typeof sm === "string" ? sm : "";
      foundInit = true;
    } else if (kind === 2) {
      const k = record["k"];
      const v = record["v"];

      if (isStringArray(k) && arraysEqual(k, ["requests"]) && Array.isArray(v)) {
        // Full snapshot — reset accumulated state.
        snapshotRequests = (v as unknown[]).filter(isRawRequest);
        responsePatches.clear();
      } else if (
        Array.isArray(k) &&
        k.length === 3 &&
        k[0] === "requests" &&
        typeof k[1] === "number" &&
        k[2] === "response" &&
        Array.isArray(v)
      ) {
        // Incremental response patch for request at index k[1].
        const idx = k[1] as number;
        const existing = responsePatches.get(idx) ?? [];
        responsePatches.set(idx, existing.concat(v as RawResponseItem[]));
      }
    }
  }

  if (!foundInit) {
    return null;
  }

  // Apply collected patches to the snapshot.
  for (const [idx, chunks] of responsePatches) {
    if (idx < snapshotRequests.length) {
      const req = snapshotRequests[idx]!;
      req.response = (req.response ?? []).concat(chunks);
    }
  }

  return {
    sessionId,
    creationDate,
    selectedModel,
    requests: snapshotRequests.map(buildRequest),
  };
}

// ---------------------------------------------------------------------------
// Internal types and helpers
// ---------------------------------------------------------------------------

interface RawResponseItem {
  kind?: unknown;
  value?: unknown;
}

interface RawRequest {
  requestId?: unknown;
  timestamp?: unknown;
  modelId?: unknown;
  message?: { text?: unknown };
  response?: RawResponseItem[];
  timeSpentWaiting?: unknown;
}

function isRawRequest(x: unknown): x is RawRequest {
  return typeof x === "object" && x !== null;
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === "string");
}

function arraysEqual(a: unknown[], b: unknown[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/**
 * Normalize a request timestamp to Unix ms.
 * Handles numeric ms and ISO 8601 strings; returns 0 on failure.
 */
function normalizeTimestamp(raw: unknown): number {
  if (typeof raw === "number" && isFinite(raw)) {
    return raw;
  }
  if (typeof raw === "string" && raw.trim().length > 0) {
    const ms = Date.parse(raw);
    if (!isNaN(ms)) {
      return ms;
    }
  }
  return 0;
}

/**
 * Normalize a creationDate value to an ISO 8601 string.
 * VS Code stores it as either a Unix timestamp in milliseconds (number) or an ISO 8601 string.
 */
function normalizeCreationDate(raw: unknown): string {
  if (typeof raw === "number" && isFinite(raw)) {
    return new Date(raw).toISOString();
  }
  return typeof raw === "string" ? raw : "";
}

/** Concatenate markdown answer chunks from a response array. */
function extractMarkdownText(response: RawResponseItem[]): string {
  const parts: string[] = [];
  for (const chunk of response) {
    const kind = chunk.kind;
    const value = chunk.value;
    if (typeof value === "string" && (kind === undefined || kind === null || kind === "markdownContent")) {
      parts.push(value);
    }
  }
  return parts.join("");
}

/** Convert raw response items to typed ResponseChunk objects. */
function normalizeResponseChunks(response: RawResponseItem[]): ResponseChunk[] {
  const chunks: ResponseChunk[] = [];
  for (const item of response) {
    const value = item.value;
    const rawKind = item.kind;
    if (typeof value === "string") {
      chunks.push({
        value,
        kind: typeof rawKind === "string" ? rawKind : "",
      });
    }
  }
  return chunks;
}

/** Convert a raw request dict from a kind=2 snapshot to ParsedRequest. */
function buildRequest(raw: RawRequest): ParsedRequest {
  const response = raw.response ?? [];
  const messageText =
    raw.message && typeof raw.message.text === "string" ? raw.message.text : "";
  const ts = raw.timestamp;
  const timeSpentWaiting = raw.timeSpentWaiting;

  return {
    requestId: typeof raw.requestId === "string" ? raw.requestId : "",
    timestamp: normalizeTimestamp(ts),
    modelId: typeof raw.modelId === "string" ? raw.modelId : "",
    messageText,
    responseText: extractMarkdownText(response),
    responseChunks: normalizeResponseChunks(response),
    timeSpentWaiting: typeof timeSpentWaiting === "number" ? timeSpentWaiting : 0,
  };
}
