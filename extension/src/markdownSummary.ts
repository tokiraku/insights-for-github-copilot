// Converts AggregatedInsights into a Markdown string for the Chat panel.
import { AggregatedInsights } from "./models.js";

const MAX_LIST_ITEMS = 5;

/**
 * Build a Markdown summary from aggregated Copilot Insights data.
 *
 * Produces six sections: Stats, What You Work On, Top Tools Used,
 * Wins, Friction, and Suggested Rules.
 *
 * @param insights - Aggregated data from loadInsights().
 * @returns A Markdown string ready to pass to ChatResponseStream.markdown().
 */
export function buildSummary(insights: AggregatedInsights): string {
  const sections: string[] = [
    buildHeader(),
    buildStats(insights),
    buildProjectAreas(insights),
    buildTopTools(insights),
    buildWins(insights),
    buildFriction(insights),
    buildSuggestedRules(insights),
    buildReportFooter(),
  ];
  return sections.join("\n\n");
}

// ---------------------------------------------------------------------------
// Section builders
// ---------------------------------------------------------------------------

function buildHeader(): string {
  return "## Copilot Insights Summary";
}

function buildStats(insights: AggregatedInsights): string {
  const lines = [
    "### Stats",
    `| Metric | Value |`,
    `|--------|-------|`,
    `| Sessions analysed | ${insights.sessionCount} |`,
    `| Total messages | ${insights.totalMessages} |`,
    `| Input tokens | ${insights.totalInputTokens.toLocaleString()} |`,
    `| Output tokens | ${insights.totalOutputTokens.toLocaleString()} |`,
    `| Lines added | ${insights.totalLinesAdded.toLocaleString()} |`,
    `| Lines removed | ${insights.totalLinesRemoved.toLocaleString()} |`,
  ];
  return lines.join("\n");
}

function buildProjectAreas(insights: AggregatedInsights): string {
  const entries = topN(insights.projectAreaCounts, MAX_LIST_ITEMS);
  if (entries.length === 0) {
    return "### What You Work On\n_No project area data available._";
  }
  const rows = entries.map(([area, count]) => `- **${area}** (${count} session${count === 1 ? "" : "s"})`);
  return `### What You Work On\n${rows.join("\n")}`;
}

function buildTopTools(insights: AggregatedInsights): string {
  const entries = topN(insights.toolCounts, MAX_LIST_ITEMS);
  if (entries.length === 0) {
    return "### Top Tools Used\n_No tool usage data available._";
  }
  const rows = entries.map(([tool, count]) => `- \`${tool}\` — ${count} call${count === 1 ? "" : "s"}`);
  return `### Top Tools Used\n${rows.join("\n")}`;
}

function buildWins(insights: AggregatedInsights): string {
  const items = insights.wins.slice(0, MAX_LIST_ITEMS);
  if (items.length === 0) {
    return "### Wins\n_No wins recorded yet._";
  }
  return `### Wins\n${items.map((w) => `- ${w}`).join("\n")}`;
}

function buildFriction(insights: AggregatedInsights): string {
  const items = insights.frictions.slice(0, MAX_LIST_ITEMS);
  if (items.length === 0) {
    return "### Friction\n_No friction points recorded yet._";
  }
  return `### Friction\n${items.map((f) => `- ${f}`).join("\n")}`;
}

function buildSuggestedRules(insights: AggregatedInsights): string {
  const items = insights.suggestedRules.slice(0, MAX_LIST_ITEMS);
  if (items.length === 0) {
    return "### Suggested Rules\n_No rule suggestions available yet._";
  }
  const header = "### Suggested Rules\n_Consider adding these to `copilot-instructions.md`:_";
  const rows = items.map((r) => `- ${r}`).join("\n");
  return `${header}\n${rows}`;
}

function buildReportFooter(): string {
  // The clickable link is rendered by extension.ts via stream.anchor().
  // This text acts as a visual separator before the anchor button.
  return "---\n_Click the button below to open the full HTML report._";
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

/**
 * Return the top-N entries from a count record, sorted by count descending.
 *
 * @param counts - A Record mapping string keys to numeric counts.
 * @param n      - Maximum number of entries to return.
 */
function topN(counts: Record<string, number>, n: number): [string, number][] {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n);
}
