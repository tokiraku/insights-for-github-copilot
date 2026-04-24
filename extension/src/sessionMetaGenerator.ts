// Pipeline that generates .copilot-insights/session-meta/ JSON files
// from VS Code workspaceStorage .jsonl chat session files.
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

import { extractSessionMeta } from "./sessionExtractor.js";
import { parseJsonlFile } from "./sessionParser.js";
import {
  getWorkspaceStorageRoot,
  listChatSessionFiles,
  resolveWorkspaceIds,
  ScanOptions,
} from "./sessionScanner.js";

const INSIGHTS_DIR = ".copilot-insights";
const SESSION_META_DIR = "session-meta";

export interface GenerateOptions extends ScanOptions {
  /** Called after each session is processed. */
  onProgress?: (current: number, total: number) => void;
  /** VS Code cancellation token; generation stops when cancelled. */
  token?: vscode.CancellationToken;
}

/**
 * Generate `.copilot-insights/session-meta/` JSON files for the given workspace.
 *
 * Scans the VS Code workspaceStorage for chat session `.jsonl` files that
 * correspond to `workspaceRoot`, parses each one, extracts quantitative
 * metadata, and writes a JSON file per session.  Sessions that already have
 * a corresponding JSON file are skipped (incremental update).
 *
 * @param workspaceRoot - Absolute path to the VS Code workspace folder.
 * @param options       - Optional scan filters and progress callback.
 * @returns Number of new session-meta files written.
 * @throws {Error} When workspaceStorage cannot be located or no workspace ID is found.
 */
export async function generateSessionMetas(
  workspaceRoot: string,
  options: GenerateOptions = {},
): Promise<number> {
  const storageRoot = getWorkspaceStorageRoot();
  const workspaceIds = resolveWorkspaceIds(storageRoot, workspaceRoot);

  if (workspaceIds.length === 0) {
    throw new Error(
      `No workspaceStorage entry found for "${workspaceRoot}". ` +
        "Make sure this folder has been opened in VS Code at least once.",
    );
  }

  const jsonlFiles = listChatSessionFiles(storageRoot, workspaceIds, options);
  const total = jsonlFiles.length;
  const { onProgress, token } = options;

  const metaDir = path.join(workspaceRoot, INSIGHTS_DIR, SESSION_META_DIR);
  fs.mkdirSync(metaDir, { recursive: true });

  let written = 0;

  for (let i = 0; i < jsonlFiles.length; i++) {
    if (token?.isCancellationRequested) {
      break;
    }

    const filePath = jsonlFiles[i]!;
    const session = parseJsonlFile(filePath);

    if (session === null || !session.sessionId) {
      onProgress?.(i + 1, total);
      continue;
    }

    const outputPath = path.join(metaDir, `${session.sessionId}.json`);

    // Skip sessions that already have a session-meta file (incremental update).
    if (fs.existsSync(outputPath)) {
      onProgress?.(i + 1, total);
      continue;
    }

    const meta = extractSessionMeta(session);
    fs.writeFileSync(outputPath, JSON.stringify(meta, null, 2), "utf8");
    written++;

    onProgress?.(i + 1, total);
  }

  return written;
}
