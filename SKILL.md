# Copilot Insights Skill

## Overview

The `@insights` Chat Participant surfaces GitHub Copilot Chat usage analytics directly in VS Code.  
It reads the intermediate data produced by the CLI tool (`python -m copilot_insights`) from the
`.copilot-insights/` directory and presents insights without sending raw conversation data outside
your machine (NFR-002).

## Prerequisites

1. Run the CLI tool to generate session data:
   ```
   python -m copilot_insights
   ```
2. Install and enable the **Insights for GitHub Copilot** VS Code extension.

## Usage

### `/summary` — Markdown overview (default)

```
@insights /summary
@insights
```

Returns a Markdown report with:
- **Stats**: total sessions, messages, tokens, lines changed
- **What You Work On**: top project areas
- **Top Tools Used**: tool invocation breakdown
- **Wins**: recurring positive patterns from LLM analysis
- **Friction**: recurring blockers or inefficiencies
- **Suggested Rules**: recommended additions to `copilot-instructions.md`

### `/report` — Full HTML report

```
@insights /report
```

Opens a VS Code Webview panel with a visual HTML report equivalent to the CLI summary.

## Architecture

```
VS Code Chat Panel
      │  @insights /summary
      ▼
extension/src/extension.ts   ← Chat Participant handler (TypeScript)
      │  reads JSON files
      ▼
.copilot-insights/
  ├── session-meta/{id}.json  ← quantitative data (FR-002)
  └── facets/{id}.json        ← LLM-generated qualitative data (FR-003)
```

## Command Reference

| Command    | Description                                          |
|------------|------------------------------------------------------|
| `/summary` | Markdown summary in the Chat panel (default)         |
| `/report`  | Open full HTML report in a Webview panel             |

## Data Privacy

- Raw chat conversation text is **never** read or transmitted by this extension.
- All data is sourced from the pre-processed `.copilot-insights/` files generated locally by the CLI.
- `.copilot-insights/` is excluded from git tracking (`.gitignore`).
