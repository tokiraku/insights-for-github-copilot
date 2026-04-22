// VS Code extension entry point.
// Registers the @insights Chat Participant and the "Open Report" command.
import * as vscode from "vscode";

import { InsightsNotFoundError, loadInsights } from "./dataLoader.js";
import { buildSummary } from "./markdownSummary.js";
import { ReportPanel } from "./reportPanel.js";

const PARTICIPANT_ID = "copilot-insights.insights";

export function activate(context: vscode.ExtensionContext): void {
  const participant = vscode.chat.createChatParticipant(
    PARTICIPANT_ID,
    handleChatRequest,
  );
  context.subscriptions.push(participant);

  const openReportCmd = vscode.commands.registerCommand(
    "copilot-insights.openReport",
    () => {
      const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
      if (!workspaceRoot) {
        vscode.window.showErrorMessage(
          "Copilot Insights: No workspace is open.",
        );
        return;
      }
      ReportPanel.show(context, workspaceRoot);
    },
  );
  context.subscriptions.push(openReportCmd);
}

/**
 * Main handler for @insights chat requests.
 *
 * Routes `/summary` and `/report` slash commands; defaults to summary when
 * no command is specified.
 *
 * @param request  - The incoming chat request from VS Code.
 * @param _context - Conversation context (unused at this phase).
 * @param stream   - Response stream used to send Markdown back to the panel.
 * @param token    - Cancellation token.
 */
async function handleChatRequest(
  request: vscode.ChatRequest,
  _context: vscode.ChatContext,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken,
): Promise<vscode.ChatResult> {
  if (token.isCancellationRequested) {
    return {};
  }

  const command = request.command;

  if (command === "report") {
    await vscode.commands.executeCommand("copilot-insights.openReport");
    return {};
  }

  if (command !== undefined && command !== "summary") {
    stream.markdown(
      `Unknown command: \`/${command}\`. Available commands: \`/summary\`, \`/report\`.`,
    );
    return {};
  }

  // Default: /summary (when no command is given) or explicit /summary
  const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!workspaceRoot) {
    stream.markdown(
      "_No workspace is open. Please open a folder in VS Code first._",
    );
    return {};
  }

  try {
    const insights = loadInsights(workspaceRoot);
    stream.markdown(buildSummary(insights));
    stream.anchor(
      vscode.Uri.parse("command:copilot-insights.openReport"),
      "詳細レポートを表示",
    );
  } catch (err) {
    if (err instanceof InsightsNotFoundError) {
      stream.markdown(`_${err.message}_`);
    } else {
      stream.markdown(
        "_An unexpected error occurred while loading insights data._",
      );
    }
  }
  return {};
}

export function deactivate(): void {}
