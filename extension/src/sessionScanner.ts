// Locates the VS Code workspaceStorage directory for the current workspace
// and enumerates .jsonl chat session files within it.
import * as fs from "fs";
import * as path from "path";
import * as url from "url";

const WORKSPACE_STORAGE_SUBPATH = path.join("Code", "User", "workspaceStorage");
const MAX_SESSIONS = 50;
const DEFAULT_DAYS = 30;

/**
 * Options for filtering chat session files.
 */
export interface ScanOptions {
  /** Only include sessions created within this many days (default: 30). */
  days?: number;
  /** Maximum number of sessions to return (default: 50). */
  maxSessions?: number;
}

/**
 * Returns the absolute path to `%APPDATA%/Code/User/workspaceStorage`.
 *
 * @throws {Error} When `APPDATA` environment variable is not set (non-Windows).
 */
export function getWorkspaceStorageRoot(): string {
  const appData = process.env["APPDATA"];
  if (!appData) {
    throw new Error(
      "APPDATA environment variable is not set. " +
        "This extension currently supports Windows only.",
    );
  }
  return path.join(appData, WORKSPACE_STORAGE_SUBPATH);
}

/**
 * Finds the workspace storage ID that corresponds to the given workspace folder path.
 *
 * Reads `workspace.json` in each subdirectory of `workspaceStorageRoot` and compares
 * the decoded `folder` URI against the canonical form of `workspaceFolderPath`.
 * Returns all matching IDs — typically one, but multiple entries can exist when VS Code
 * has created several storage directories for the same folder.
 *
 * @param workspaceStorageRoot  - Absolute path to the `workspaceStorage` directory.
 * @param workspaceFolderPath   - Absolute path of the VS Code workspace folder.
 * @returns Array of matching workspace storage IDs (directory names).
 */
export function resolveWorkspaceIds(
  workspaceStorageRoot: string,
  workspaceFolderPath: string,
): string[] {
  if (!fs.existsSync(workspaceStorageRoot)) {
    return [];
  }

  // Normalize the workspace path for comparison (lower-case drive letter on Windows).
  const normalizedTarget = normalizeFsPath(workspaceFolderPath);

  const matchingIds: string[] = [];

  for (const entry of fs.readdirSync(workspaceStorageRoot)) {
    const workspaceJsonPath = path.join(
      workspaceStorageRoot,
      entry,
      "workspace.json",
    );
    if (!fs.existsSync(workspaceJsonPath)) {
      continue;
    }

    try {
      const raw = fs.readFileSync(workspaceJsonPath, "utf8");
      const parsed = JSON.parse(raw) as { folder?: string };
      if (!parsed.folder) {
        continue;
      }

      // Decode percent-encoded characters in the file URI (e.g. %3A → :, %20 → space).
      const folderPath = normalizeFsPath(url.fileURLToPath(parsed.folder));

      if (folderPath === normalizedTarget) {
        matchingIds.push(entry);
      }
    } catch {
      // Skip entries with malformed workspace.json.
    }
  }

  return matchingIds;
}

/**
 * Lists `.jsonl` chat session files for the given workspace storage ID(s),
 * filtered to the specified recency window and capped at `maxSessions`.
 *
 * Files are sorted newest-first (by `mtime`) before the cap is applied so
 * that the most recent sessions are always included.
 *
 * @param workspaceStorageRoot - Absolute path to the `workspaceStorage` directory.
 * @param workspaceIds         - One or more workspace storage IDs to scan.
 * @param options              - Optional filtering parameters.
 * @returns Array of absolute paths to matching `.jsonl` files.
 */
export function listChatSessionFiles(
  workspaceStorageRoot: string,
  workspaceIds: string[],
  options: ScanOptions = {},
): string[] {
  const days = options.days ?? DEFAULT_DAYS;
  const maxSessions = options.maxSessions ?? MAX_SESSIONS;
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;

  interface FileEntry {
    filePath: string;
    mtime: number;
  }

  const entries: FileEntry[] = [];

  for (const id of workspaceIds) {
    const chatSessionsDir = path.join(
      workspaceStorageRoot,
      id,
      "chatSessions",
    );
    if (!fs.existsSync(chatSessionsDir)) {
      continue;
    }

    for (const name of fs.readdirSync(chatSessionsDir)) {
      if (!name.endsWith(".jsonl")) {
        continue;
      }

      const filePath = path.join(chatSessionsDir, name);
      try {
        const stat = fs.statSync(filePath);
        if (stat.mtimeMs >= cutoff) {
          entries.push({ filePath, mtime: stat.mtimeMs });
        }
      } catch {
        // Skip files that cannot be stat-ed.
      }
    }
  }

  // Sort newest-first, then apply the session cap.
  entries.sort((a, b) => b.mtime - a.mtime);
  return entries.slice(0, maxSessions).map((e) => e.filePath);
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Normalizes a filesystem path for cross-platform comparison.
 * Path separators are unified on all platforms, and case-folding is applied
 * only on Windows where filesystem comparisons are typically case-insensitive.
 */
function normalizeFsPath(fsPath: string): string {
  const normalized = path.normalize(fsPath);
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}
