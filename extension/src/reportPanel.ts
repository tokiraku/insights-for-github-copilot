// Manages the singleton VS Code Webview panel for the HTML report (FR-005).
import * as vscode from "vscode";

import { InsightsNotFoundError, loadInsights } from "./dataLoader.js";
import { AggregatedInsights } from "./models.js";

/**
 * Singleton Webview panel that displays the full Copilot Insights HTML report.
 *
 * Call `ReportPanel.show()` to open or reveal the panel. Each call reloads the
 * latest insights data from disk and rebuilds the HTML, so the report always
 * reflects the current state of `.copilot-insights/`.
 */
export class ReportPanel {
  private static _instance: ReportPanel | undefined;

  private readonly _panel: vscode.WebviewPanel;
  private _disposables: vscode.Disposable[] = [];

  private constructor(
    panel: vscode.WebviewPanel,
    insights: AggregatedInsights,
  ) {
    this._panel = panel;
    this._panel.webview.html = buildHtml(insights);

    this._panel.onDidDispose(
      () => this._dispose(),
      null,
      this._disposables,
    );
  }

  /**
   * Open or reveal the Webview panel populated with insights loaded from
   * the workspace's `.copilot-insights/` directory.
   *
   * @param context       - Extension context, used to preserve panel lifetime.
   * @param workspaceRoot - Absolute path to the VS Code workspace root folder.
   */
  static show(
    context: vscode.ExtensionContext,
    workspaceRoot: string,
  ): void {
    let insights: AggregatedInsights;
    try {
      insights = loadInsights(workspaceRoot);
    } catch (err) {
      if (err instanceof InsightsNotFoundError) {
        vscode.window.showErrorMessage(err.message);
      } else {
        vscode.window.showErrorMessage(
          "Copilot Insights: Failed to load report data.",
        );
      }
      return;
    }

    if (ReportPanel._instance) {
      ReportPanel._instance._panel.webview.html = buildHtml(insights);
      ReportPanel._instance._panel.reveal();
      return;
    }

    const panel = vscode.window.createWebviewPanel(
      "copilotInsightsReport",
      "Copilot Insights Report",
      vscode.ViewColumn.One,
      { enableScripts: false },
    );

    ReportPanel._instance = new ReportPanel(panel, insights);
    context.subscriptions.push(panel);
  }

  private _dispose(): void {
    ReportPanel._instance = undefined;
    for (const d of this._disposables) {
      d.dispose();
    }
    this._disposables = [];
  }
}

// ---------------------------------------------------------------------------
// HTML generation
// ---------------------------------------------------------------------------

const MAX_LIST_ITEMS = 10;

/**
 * Build the full HTML document for the Webview panel.
 *
 * Renders seven sections: Stats, What You Work On, Top Tools Used,
 * Languages, Wins, Friction, and Suggested Rules.
 *
 * @param insights - Aggregated insights data to render.
 * @returns Complete HTML string ready to assign to WebviewPanel.webview.html.
 */
function buildHtml(insights: AggregatedInsights): string {
  const sections = [
    buildStatsSection(insights),
    buildProjectAreasSection(insights),
    buildTopToolsSection(insights),
    buildLanguagesSection(insights),
    buildWinsSection(insights),
    buildFrictionSection(insights),
    buildSuggestedRulesSection(insights),
  ].join("\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
  <title>Copilot Insights Report</title>
  <style>
    /* ---- Base ---- */
    *, *::before, *::after { box-sizing: border-box; }
    body {
      font-family: var(--vscode-font-family, sans-serif);
      font-size: var(--vscode-font-size, 13px);
      line-height: 1.5;
      color: var(--vscode-foreground);
      background-color: var(--vscode-editor-background);
      padding: 28px 32px;
      margin: 0;
      max-width: 900px;
    }

    /* ---- Headings ---- */
    h1 {
      font-size: 1.5em;
      font-weight: 600;
      margin: 0 0 0.15em;
      color: var(--vscode-foreground);
    }
    h2 {
      font-size: 1.05em;
      font-weight: 600;
      margin: 2em 0 0.5em;
      padding-bottom: 0.3em;
      border-bottom: 1px solid var(--vscode-widget-border, rgba(128,128,128,0.35));
      color: var(--vscode-foreground);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    /* ---- Subtitle ---- */
    p.subtitle {
      color: var(--vscode-descriptionForeground);
      margin: 0 0 2em;
      font-size: 0.95em;
    }

    /* ---- Tables ---- */
    table {
      border-collapse: collapse;
      width: 100%;
      margin-bottom: 0.25em;
    }
    th, td {
      text-align: left;
      padding: 5px 12px;
      border: 1px solid var(--vscode-widget-border, rgba(128,128,128,0.35));
    }
    th {
      background-color: var(--vscode-editor-lineHighlightBackground, rgba(128,128,128,0.1));
      font-weight: 600;
      font-size: 0.9em;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      color: var(--vscode-descriptionForeground);
    }
    /* Right-align numeric column (second column) */
    td:last-child, th:last-child { text-align: right; min-width: 60px; }
    /* Stripe even rows */
    tbody tr:nth-child(even) {
      background-color: var(--vscode-editor-lineHighlightBackground, rgba(128,128,128,0.06));
    }
    tbody tr:hover {
      background-color: var(--vscode-list-hoverBackground, rgba(128,128,128,0.12));
    }

    /* ---- Lists ---- */
    ul {
      margin: 0;
      padding-left: 1.3em;
    }
    li {
      margin: 4px 0;
      line-height: 1.45;
    }
    /* Wins: green accent marker */
    .wins-list li::marker { color: var(--vscode-charts-green, #4caf50); }
    /* Friction: orange/red accent marker */
    .friction-list li::marker { color: var(--vscode-charts-orange, #ff9800); }
    /* Suggested rules: blue accent marker */
    .rules-list li::marker { color: var(--vscode-charts-blue, #2196f3); }

    /* ---- Inline code ---- */
    code {
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: 0.9em;
      background: var(--vscode-textCodeBlock-background, rgba(128,128,128,0.18));
      color: var(--vscode-textPreformat-foreground, inherit);
      padding: 1px 5px;
      border-radius: 3px;
    }

    /* ---- Empty state ---- */
    .empty {
      color: var(--vscode-descriptionForeground);
      font-style: italic;
    }

    /* ---- Hint text (above suggested rules list) ---- */
    p.hint {
      color: var(--vscode-descriptionForeground);
      font-size: 0.9em;
      margin: 0.3em 0 0.5em;
    }
  </style>
</head>
<body>
  <h1>Copilot Insights Report</h1>
  <p class="subtitle">${insights.sessionCount} session${insights.sessionCount === 1 ? "" : "s"} analysed</p>
  ${sections}
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Section builders
// ---------------------------------------------------------------------------

function buildStatsSection(insights: AggregatedInsights): string {
  return `<h2>Stats</h2>
<table>
  <thead><tr><th>Metric</th><th>Value</th></tr></thead>
  <tbody>
    <tr><td>Sessions analysed</td><td>${insights.sessionCount}</td></tr>
    <tr><td>Total messages</td><td>${insights.totalMessages.toLocaleString()}</td></tr>
    <tr><td>Input tokens</td><td>${insights.totalInputTokens.toLocaleString()}</td></tr>
    <tr><td>Output tokens</td><td>${insights.totalOutputTokens.toLocaleString()}</td></tr>
    <tr><td>Lines added</td><td>${insights.totalLinesAdded.toLocaleString()}</td></tr>
    <tr><td>Lines removed</td><td>${insights.totalLinesRemoved.toLocaleString()}</td></tr>
  </tbody>
</table>`;
}

function buildProjectAreasSection(insights: AggregatedInsights): string {
  const entries = topN(insights.projectAreaCounts, MAX_LIST_ITEMS);
  if (entries.length === 0) {
    return `<h2>What You Work On</h2><p class="empty">No project area data available.</p>`;
  }
  const rows = entries
    .map(([area, count]) => `<tr><td>${esc(area)}</td><td>${count}</td></tr>`)
    .join("\n    ");
  return `<h2>What You Work On</h2>
<table>
  <thead><tr><th>Project Area</th><th>Sessions</th></tr></thead>
  <tbody>
    ${rows}
  </tbody>
</table>`;
}

function buildTopToolsSection(insights: AggregatedInsights): string {
  const entries = topN(insights.toolCounts, MAX_LIST_ITEMS);
  if (entries.length === 0) {
    return `<h2>Top Tools Used</h2><p class="empty">No tool usage data available.</p>`;
  }
  const rows = entries
    .map(([tool, count]) => `<tr><td><code>${esc(tool)}</code></td><td>${count}</td></tr>`)
    .join("\n    ");
  return `<h2>Top Tools Used</h2>
<table>
  <thead><tr><th>Tool</th><th>Calls</th></tr></thead>
  <tbody>
    ${rows}
  </tbody>
</table>`;
}

function buildLanguagesSection(insights: AggregatedInsights): string {
  const entries = topN(insights.languageCounts, MAX_LIST_ITEMS);
  if (entries.length === 0) {
    return `<h2>Languages</h2><p class="empty">No language data available.</p>`;
  }
  const rows = entries
    .map(([lang, count]) => `<tr><td>${esc(lang)}</td><td>${count}</td></tr>`)
    .join("\n    ");
  return `<h2>Languages</h2>
<table>
  <thead><tr><th>Language</th><th>Sessions</th></tr></thead>
  <tbody>
    ${rows}
  </tbody>
</table>`;
}

function buildWinsSection(insights: AggregatedInsights): string {
  const items = insights.wins.slice(0, MAX_LIST_ITEMS);
  if (items.length === 0) {
    return `<h2>Wins</h2><p class="empty">No wins recorded yet.</p>`;
  }
  const lis = items.map((w) => `<li>${esc(w)}</li>`).join("\n    ");
  return `<h2>Wins</h2><ul class="wins-list">\n    ${lis}\n  </ul>`;
}

function buildFrictionSection(insights: AggregatedInsights): string {
  const items = insights.frictions.slice(0, MAX_LIST_ITEMS);
  if (items.length === 0) {
    return `<h2>Friction</h2><p class="empty">No friction points recorded yet.</p>`;
  }
  const lis = items.map((f) => `<li>${esc(f)}</li>`).join("\n    ");
  return `<h2>Friction</h2><ul class="friction-list">\n    ${lis}\n  </ul>`;
}

function buildSuggestedRulesSection(insights: AggregatedInsights): string {
  const items = insights.suggestedRules.slice(0, MAX_LIST_ITEMS);
  if (items.length === 0) {
    return `<h2>Suggested Rules</h2><p class="empty">No rule suggestions available yet.</p>`;
  }
  const lis = items.map((r) => `<li>${esc(r)}</li>`).join("\n    ");
  return `<h2>Suggested Rules</h2>
<p class="hint">Consider adding these to <code>copilot-instructions.md</code>:</p>
<ul class="rules-list">\n    ${lis}\n  </ul>`;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

/** Return top-N entries from a count record, sorted by count descending. */
function topN(counts: Record<string, number>, n: number): [string, number][] {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n);
}

/**
 * Escape special HTML characters to prevent XSS when embedding user-derived
 * strings (project areas, tool names, wins, etc.) into the Webview HTML.
 */
function esc(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
