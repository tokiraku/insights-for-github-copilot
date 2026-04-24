// Unit tests for sessionParser.ts — TypeScript port of test_parser.py.
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { parseJsonlFile } from "./sessionParser.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

let tmpDir: string;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "parser-test-"));
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function writeJsonl(name: string, lines: object[]): string {
  const filePath = path.join(tmpDir, name);
  fs.writeFileSync(filePath, lines.map((l) => JSON.stringify(l)).join("\n"), "utf8");
  return filePath;
}

function initLine(
  sessionId = "sess-001",
  creationDate: string | number = "2026-04-01T10:00:00.000Z",
  selectedModel = "gpt-4o",
) {
  return { kind: 0, v: { sessionId, creationDate, selectedModel } };
}

function snapshotLine(requests: object[]) {
  return { kind: 2, k: ["requests"], v: requests };
}

function responsePatchLine(index: number, chunks: object[]) {
  return { kind: 2, k: ["requests", index, "response"], v: chunks };
}

function makeRequest(opts: {
  requestId?: string;
  timestamp?: number;
  messageText?: string;
  response?: object[];
  timeSpentWaiting?: number;
} = {}) {
  return {
    requestId: opts.requestId ?? "req-1",
    timestamp: opts.timestamp ?? 1743508800000,
    agent: "copilot",
    modelId: "gpt-4o",
    message: { text: opts.messageText ?? "Hello" },
    response: opts.response ?? [],
    timeSpentWaiting: opts.timeSpentWaiting ?? 1200,
  };
}

// ---------------------------------------------------------------------------
// Basic success cases
// ---------------------------------------------------------------------------

describe("parseJsonlFile — basic", () => {
  it("returns session with correct metadata", () => {
    const filePath = writeJsonl("session.jsonl", [
      initLine("s1", "2026-04-01T10:00:00Z", "gpt-4o"),
      snapshotLine([]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result).not.toBeNull();
    expect(result!.sessionId).toBe("s1");
    expect(result!.creationDate).toBe("2026-04-01T10:00:00Z");
    expect(result!.selectedModel).toBe("gpt-4o");
  });

  it("returns null when no kind=0 line", () => {
    const filePath = writeJsonl("no_init.jsonl", [snapshotLine([makeRequest()])]);
    expect(parseJsonlFile(filePath)).toBeNull();
  });

  it("returns null for nonexistent file", () => {
    expect(parseJsonlFile(path.join(tmpDir, "missing.jsonl"))).toBeNull();
  });

  it("returns null for non-JSON content", () => {
    const filePath = path.join(tmpDir, "bad.jsonl");
    fs.writeFileSync(filePath, "not json at all\n", "utf8");
    expect(parseJsonlFile(filePath)).toBeNull();
  });

  it("returns empty requests when no snapshot", () => {
    const filePath = writeJsonl("session.jsonl", [initLine()]);
    const result = parseJsonlFile(filePath);
    expect(result).not.toBeNull();
    expect(result!.requests).toEqual([]);
  });

  it("normalizes Unix ms creationDate to ISO string", () => {
    const ms = 1743508800000; // 2026-04-01T00:00:00.000Z
    const filePath = writeJsonl("session.jsonl", [initLine("s1", ms), snapshotLine([])]);
    const result = parseJsonlFile(filePath);
    expect(result).not.toBeNull();
    expect(result!.creationDate).toBe(new Date(ms).toISOString());
  });
});

// ---------------------------------------------------------------------------
// Request extraction
// ---------------------------------------------------------------------------

describe("parseJsonlFile — request extraction", () => {
  it("extracts message text", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ messageText: "What is Python?" })]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests[0]!.messageText).toBe("What is Python?");
  });

  it("extracts markdown response from snapshot", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ response: [{ value: "Python is great." }] })]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests[0]!.responseText).toBe("Python is great.");
  });

  it("concatenates multiple markdown chunks", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ response: [{ value: "Hello " }, { value: "world." }] })]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests[0]!.responseText).toBe("Hello world.");
  });

  it("excludes non-markdown chunks from responseText", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({
        response: [
          { value: "Answer.", kind: "markdownContent" },
          { value: "<tool>", kind: "toolInvocationSerialized" },
          { value: "thinking...", kind: "thinking" },
        ],
      })]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests[0]!.responseText).toBe("Answer.");
  });

  it("extracts request metadata", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ requestId: "r1", timestamp: 1743508800000, timeSpentWaiting: 1200 })]),
    ]);
    const result = parseJsonlFile(filePath);
    const r = result!.requests[0]!;
    expect(r.requestId).toBe("r1");
    expect(r.timestamp).toBe(1743508800000);
    expect(r.modelId).toBe("gpt-4o");
    expect(r.timeSpentWaiting).toBe(1200);
  });

  it("preserves multiple requests", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([
        makeRequest({ requestId: "r1", messageText: "Q1" }),
        makeRequest({ requestId: "r2", messageText: "Q2" }),
      ]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests).toHaveLength(2);
    expect(result!.requests[0]!.requestId).toBe("r1");
    expect(result!.requests[1]!.requestId).toBe("r2");
  });
});

// ---------------------------------------------------------------------------
// Snapshot / patch semantics
// ---------------------------------------------------------------------------

describe("parseJsonlFile — snapshot/patch semantics", () => {
  it("last snapshot wins", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ requestId: "old", messageText: "old" })]),
      snapshotLine([makeRequest({ requestId: "new", messageText: "new" })]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests).toHaveLength(1);
    expect(result!.requests[0]!.requestId).toBe("new");
  });

  it("response patch appended to snapshot response", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ response: [{ value: "Part1 " }] })]),
      responsePatchLine(0, [{ value: "Part2." }]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests[0]!.responseText).toBe("Part1 Part2.");
  });

  it("multiple response patches accumulated", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ response: [] })]),
      responsePatchLine(0, [{ value: "A" }]),
      responsePatchLine(0, [{ value: "B" }]),
      responsePatchLine(0, [{ value: "C" }]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests[0]!.responseText).toBe("ABC");
  });

  it("patches reset on new snapshot", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ requestId: "old", response: [] })]),
      responsePatchLine(0, [{ value: "Stale patch" }]),
      snapshotLine([makeRequest({ requestId: "new", response: [{ value: "Fresh." }] })]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests).toHaveLength(1);
    expect(result!.requests[0]!.requestId).toBe("new");
    expect(result!.requests[0]!.responseText).toBe("Fresh.");
  });

  it("patch for out-of-bounds index is ignored", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ response: [] })]),
      responsePatchLine(99, [{ value: "ghost" }]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests[0]!.responseText).toBe("");
  });

  it("kind=1 lines are ignored", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      { kind: 1, v: { inputText: "user is typing..." } },
      snapshotLine([makeRequest({ requestId: "r1" })]),
    ]);
    const result = parseJsonlFile(filePath);
    expect(result!.requests).toHaveLength(1);
  });

  it("invalid JSON lines are skipped", () => {
    const filePath = path.join(tmpDir, "s.jsonl");
    fs.writeFileSync(
      filePath,
      [
        JSON.stringify(initLine()),
        "{ this is not valid json }",
        JSON.stringify(snapshotLine([makeRequest({ requestId: "r1" })])),
      ].join("\n"),
      "utf8",
    );
    const result = parseJsonlFile(filePath);
    expect(result).not.toBeNull();
    expect(result!.requests).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// responseChunks field
// ---------------------------------------------------------------------------

describe("parseJsonlFile — responseChunks", () => {
  it("includes all kinds in responseChunks", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({
        response: [
          { value: "Answer.", kind: "markdownContent" },
          { value: "<tool>", kind: "toolInvocationSerialized" },
        ],
      })]),
    ]);
    const result = parseJsonlFile(filePath);
    const chunks = result!.requests[0]!.responseChunks;
    expect(chunks).toHaveLength(2);
    const kinds = new Set(chunks.map((c) => c.kind));
    expect(kinds.has("markdownContent")).toBe(true);
    expect(kinds.has("toolInvocationSerialized")).toBe(true);
  });

  it("chunk without kind gets empty string", () => {
    const filePath = writeJsonl("s.jsonl", [
      initLine(),
      snapshotLine([makeRequest({ response: [{ value: "plain markdown" }] })]),
    ]);
    const result = parseJsonlFile(filePath);
    const chunk = result!.requests[0]!.responseChunks[0]!;
    expect(chunk.kind).toBe("");
    expect(chunk.value).toBe("plain markdown");
  });
});
