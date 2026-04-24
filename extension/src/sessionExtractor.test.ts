// Unit tests for sessionExtractor.ts — TypeScript port of test_extractor.py.
import { describe, expect, it } from "vitest";
import { extractSessionMeta } from "./sessionExtractor.js";
import { ParsedRequest, ParsedSession } from "./sessionParser.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeChunk(value: string, kind = "") {
  return { value, kind };
}

function toolChunk(invocation: object) {
  return { value: JSON.stringify(invocation), kind: "toolInvocationSerialized" };
}

function makeRequest(opts: {
  requestId?: string;
  timestamp?: number;
  messageText?: string;
  responseText?: string;
  responseChunks?: ReturnType<typeof makeChunk>[];
  timeSpentWaiting?: number;
} = {}): ParsedRequest {
  return {
    requestId: opts.requestId ?? "r1",
    timestamp: opts.timestamp ?? 1743508800000,
    modelId: "gpt-4o",
    messageText: opts.messageText ?? "Hello",
    responseText: opts.responseText ?? "World",
    responseChunks: opts.responseChunks ?? [],
    timeSpentWaiting: opts.timeSpentWaiting ?? 0,
  };
}

function makeSession(opts: {
  sessionId?: string;
  creationDate?: string;
  requests?: ParsedRequest[];
} = {}): ParsedSession {
  return {
    sessionId: opts.sessionId ?? "sess-001",
    creationDate: opts.creationDate ?? "2026-04-01T10:00:00.000Z",
    selectedModel: "gpt-4o",
    requests: opts.requests ?? [],
  };
}

// ---------------------------------------------------------------------------
// schema_version and session_id
// ---------------------------------------------------------------------------

describe("extractSessionMeta — schema_version and session_id", () => {
  it("schema_version is set", () => {
    const meta = extractSessionMeta(makeSession());
    expect(meta.schema_version).toBe("1.0");
  });

  it("session_id matches input", () => {
    const meta = extractSessionMeta(makeSession({ sessionId: "abc-123" }));
    expect(meta.session_id).toBe("abc-123");
  });

  it("start_time matches creation_date", () => {
    const meta = extractSessionMeta(makeSession({ creationDate: "2026-04-01T09:00:00Z" }));
    expect(meta.start_time).toBe("2026-04-01T09:00:00Z");
  });
});

// ---------------------------------------------------------------------------
// user_message_count
// ---------------------------------------------------------------------------

describe("extractSessionMeta — user_message_count", () => {
  it("zero requests", () => {
    expect(extractSessionMeta(makeSession({ requests: [] })).user_message_count).toBe(0);
  });

  it("single request", () => {
    expect(extractSessionMeta(makeSession({ requests: [makeRequest()] })).user_message_count).toBe(1);
  });

  it("multiple requests", () => {
    const reqs = Array.from({ length: 5 }, (_, i) => makeRequest({ requestId: `r${i}` }));
    expect(extractSessionMeta(makeSession({ requests: reqs })).user_message_count).toBe(5);
  });
});

// ---------------------------------------------------------------------------
// duration_minutes and user_response_times
// ---------------------------------------------------------------------------

describe("extractSessionMeta — duration and response times", () => {
  it("zero duration when no requests", () => {
    expect(extractSessionMeta(makeSession({ requests: [] })).duration_minutes).toBe(0);
  });

  it("zero duration when single request", () => {
    expect(extractSessionMeta(makeSession({ requests: [makeRequest()] })).duration_minutes).toBe(0);
  });

  it("duration computed from Unix ms timestamps (10 minutes)", () => {
    const t0 = 1_743_508_800_000;
    const t1 = t0 + 600_000; // +10 minutes
    const reqs = [
      makeRequest({ requestId: "r1", timestamp: t0 }),
      makeRequest({ requestId: "r2", timestamp: t1 }),
    ];
    const meta = extractSessionMeta(makeSession({ requests: reqs }));
    expect(meta.duration_minutes).toBeCloseTo(10.0, 1);
  });

  it("user_response_times empty when single request", () => {
    expect(extractSessionMeta(makeSession({ requests: [makeRequest()] })).user_response_times).toEqual([]);
  });

  it("user_response_times between consecutive messages", () => {
    const t0 = 1_743_508_800_000;
    const reqs = [
      makeRequest({ requestId: "r1", timestamp: t0 }),
      makeRequest({ requestId: "r2", timestamp: t0 + 60_000 }),  // +60s
      makeRequest({ requestId: "r3", timestamp: t0 + 90_000 }),  // +30s
    ];
    const meta = extractSessionMeta(makeSession({ requests: reqs }));
    expect(meta.user_response_times).toHaveLength(2);
    expect(meta.user_response_times[0]).toBeCloseTo(60.0, 1);
    expect(meta.user_response_times[1]).toBeCloseTo(30.0, 1);
  });
});

// ---------------------------------------------------------------------------
// message_hours
// ---------------------------------------------------------------------------

describe("extractSessionMeta — message_hours", () => {
  it("empty when no requests", () => {
    expect(extractSessionMeta(makeSession({ requests: [] })).message_hours).toEqual([]);
  });

  it("hours extracted from Unix ms timestamps", () => {
    // 2026-04-01T09:00:00Z = 1743498000000
    const t9  = 1_743_498_000_000;
    // 2026-04-01T22:00:00Z = 1743544800000
    const t22 = 1_743_544_800_000;
    const reqs = [
      makeRequest({ requestId: "r1", timestamp: t9 }),
      makeRequest({ requestId: "r2", timestamp: t22 }),
    ];
    const meta = extractSessionMeta(makeSession({ requests: reqs }));
    expect(meta.message_hours[0]).toBe(9);
    expect(meta.message_hours[1]).toBe(22);
  });
});

// ---------------------------------------------------------------------------
// tool_counts
// ---------------------------------------------------------------------------

describe("extractSessionMeta — tool_counts", () => {
  it("empty when no tool chunks", () => {
    const req = makeRequest({ responseChunks: [makeChunk("answer", "markdownContent")] });
    expect(extractSessionMeta(makeSession({ requests: [req] })).tool_counts).toEqual({});
  });

  it("counts tool by toolName key", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Read", input: {} })] });
    expect(extractSessionMeta(makeSession({ requests: [req] })).tool_counts).toEqual({ Read: 1 });
  });

  it("counts tool by name key as fallback", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ name: "Bash", input: {} })] });
    expect(extractSessionMeta(makeSession({ requests: [req] })).tool_counts).toEqual({ Bash: 1 });
  });

  it("aggregates counts across requests", () => {
    const reqs = [
      makeRequest({ requestId: "r1", responseChunks: [toolChunk({ toolName: "Read" }), toolChunk({ toolName: "Read" })] }),
      makeRequest({ requestId: "r2", responseChunks: [toolChunk({ toolName: "Write" })] }),
    ];
    const meta = extractSessionMeta(makeSession({ requests: reqs }));
    expect(meta.tool_counts["Read"]).toBe(2);
    expect(meta.tool_counts["Write"]).toBe(1);
  });

  it("ignores invalid JSON in tool chunk", () => {
    const badChunk = { value: "not json", kind: "toolInvocationSerialized" };
    const req = makeRequest({ responseChunks: [badChunk] });
    expect(extractSessionMeta(makeSession({ requests: [req] })).tool_counts).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// tool_errors
// ---------------------------------------------------------------------------

describe("extractSessionMeta — tool_errors", () => {
  it("zero errors when no tool chunks", () => {
    expect(extractSessionMeta(makeSession({ requests: [makeRequest()] })).tool_errors).toBe(0);
  });

  it("detects string error result", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Bash", result: "error: command not found" })] });
    expect(extractSessionMeta(makeSession({ requests: [req] })).tool_errors).toBe(1);
  });

  it("detects dict isError result", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Read", result: { isError: true } })] });
    expect(extractSessionMeta(makeSession({ requests: [req] })).tool_errors).toBe(1);
  });

  it("no error for successful result", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Read", result: "file contents" })] });
    expect(extractSessionMeta(makeSession({ requests: [req] })).tool_errors).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// files_modified and languages
// ---------------------------------------------------------------------------

describe("extractSessionMeta — files_modified and languages", () => {
  it("empty when no file paths in tool input", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Bash", input: { command: "ls" } })] });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.files_modified).toEqual([]);
    expect(meta.languages).toEqual([]);
  });

  it("extracts file_path key", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Read", input: { file_path: "src/main.py" } })] });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.files_modified).toContain("src/main.py");
    expect(meta.languages).toContain("Python");
  });

  it("extracts path key", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Write", input: { path: "index.ts", content: "export {}\n" } })] });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.files_modified).toContain("index.ts");
    expect(meta.languages).toContain("TypeScript");
  });

  it("deduplicates files", () => {
    const req = makeRequest({
      responseChunks: [
        toolChunk({ toolName: "Read", input: { file_path: "src/app.py" } }),
        toolChunk({ toolName: "Write", input: { file_path: "src/app.py", content: "x\n" } }),
      ],
    });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.files_modified.filter((f) => f === "src/app.py")).toHaveLength(1);
  });

  it("languages sorted by frequency", () => {
    const req = makeRequest({
      responseChunks: [
        toolChunk({ toolName: "Read", input: { file_path: "a.py" } }),
        toolChunk({ toolName: "Read", input: { file_path: "b.py" } }),
        toolChunk({ toolName: "Read", input: { file_path: "c.ts" } }),
      ],
    });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.languages[0]).toBe("Python");
  });

  it("unknown extension is capitalized", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Write", input: { file_path: "config.xyz" } })] });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.languages).toContain("Xyz");
  });
});

// ---------------------------------------------------------------------------
// lines_added / lines_removed
// ---------------------------------------------------------------------------

describe("extractSessionMeta — lines_added / lines_removed", () => {
  it("zeros when no tool chunks", () => {
    const meta = extractSessionMeta(makeSession({ requests: [makeRequest()] }));
    expect(meta.lines_added).toBe(0);
    expect(meta.lines_removed).toBe(0);
  });

  it("write tool counts content lines as added", () => {
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Write", input: { content: "line1\nline2\nline3" } })] });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.lines_added).toBe(3);
    expect(meta.lines_removed).toBe(0);
  });

  it("edit tool counts new and old strings", () => {
    const req = makeRequest({
      responseChunks: [toolChunk({ toolName: "Edit", input: { new_string: "a\nb\nc", old_string: "x\ny" } })],
    });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.lines_added).toBe(3);
    expect(meta.lines_removed).toBe(2);
  });

  it("diff field parsed correctly", () => {
    const diff = "+++ b/file.py\n+added line\n-removed line\n--- a/file.py\n context";
    const req = makeRequest({ responseChunks: [toolChunk({ toolName: "Patch", input: { diff } })] });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.lines_added).toBe(1);
    expect(meta.lines_removed).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// input_tokens / output_tokens
// ---------------------------------------------------------------------------

describe("extractSessionMeta — token estimates", () => {
  it("minimum one token when no text", () => {
    const req = makeRequest({ messageText: "", responseText: "" });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.input_tokens).toBeGreaterThanOrEqual(1);
    expect(meta.output_tokens).toBeGreaterThanOrEqual(1);
  });

  it("tokens proportional to text length (÷4)", () => {
    const req = makeRequest({ messageText: "a".repeat(40), responseText: "b".repeat(80) });
    const meta = extractSessionMeta(makeSession({ requests: [req] }));
    expect(meta.input_tokens).toBe(10);
    expect(meta.output_tokens).toBe(20);
  });

  it("tokens summed across requests", () => {
    const reqs = [
      makeRequest({ requestId: "r1", messageText: "a".repeat(40), responseText: "b".repeat(40) }),
      makeRequest({ requestId: "r2", messageText: "c".repeat(40), responseText: "d".repeat(40) }),
    ];
    const meta = extractSessionMeta(makeSession({ requests: reqs }));
    expect(meta.input_tokens).toBe(20);
    expect(meta.output_tokens).toBe(20);
  });
});
