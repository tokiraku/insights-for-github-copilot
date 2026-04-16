# GitHub Copilot向け「insights」機能 要件定義

## 1. 背景・目的

Claude Code の `/insights` コマンド相当の機能を GitHub Copilot 上に実装する。
ユーザーの Copilot 利用状況を分析し、プロンプトの改善やルールファイル（`copilot-instructions.md` 等）への提案を行うことが主目的。

---

## 2. 参照仕様：Claude Code の `/insights` コマンド

### 2.1 分析対象

- 過去 30 日間（最大 50 セッション）のセッションログ（対話履歴）

### 2.2 出力内容（`claude-code-insights.html` の構成）

| セクション | 内容 |
|---|---|
| 全体統計 (Stats) | メッセージ総数、追加/削除行数、対象ファイル数、利用日数、1日あたりの平均メッセージ数 |
| プロジェクト領域 (What You Work On) | タスク種別ごとのセッション数要約 |
| 目的 (What You Wanted) | バグ修正、ドキュメント更新など |
| 使用ツール (Top Tools Used) | コマンド実行、ファイル編集、検索など |
| 言語 (Languages) | Markdown, Python, TypeScript など |
| セッションタイプ | マルチタスク / 単一タスク |
| 利用スタイル (How You Use...) | 応答時間分布、並行セッション、時間帯別活動傾向、エラー分類 |
| 成功パターン (Wins) | 良かった進め方の具体的テキスト |
| 摩擦 (Friction) | 失敗・手戻りが発生したパターン |
| 改善提案 | ルールファイルへの追記案、プロンプト改善案 |

### 2.3 中間データ

- `.claude/usage-data/session-meta` — セッションのメタデータ（定量）
- `.claude/usage-data/facets` — 分析の切り口・特徴量データ（定性）

---

## 3. アーキテクチャ

**ハイブリッド構成（CLI解析 + Copilot Chat エージェント/スキル）** を採用する。

```
[ローカル chatSessions JSON]
        │
        ▼
[CLIツール / ローカルプロセス]  ← バックエンド
  ・JSONを抽出・パース
  ・LLM API で定性分析
  ・中間データを .copilot-insights/ に保存
        │
        ▼
[.copilot-insights/session-meta/*.json]
[.copilot-insights/facets/*.json]
        │
        ▼
[Copilot Chat エージェント / スキル]  ← フロントエンド
  ・中間JSONを読み取り
  ・チャットパネルに Markdown サマリを返答
  ・Webview で HTML レポートをレンダリング
```

### メリット

- データパイプライン（解析）とプレゼンテーション（表示）の関心を完全分離
- 保守・テストが容易
- ユーザーは Copilot Chat から既存のワークフローとシームレスに利用可能

---

## 4. 要件定義

### 4.1 分析の主目的

- ユーザーの Copilot 利用状況を分析する
- プロンプトの改善提案を行う
- ルールファイル（`copilot-instructions.md` 等）への具体的な追記内容を提案する

### 4.2 データソース

- VS Code のローカルストレージに保存された GitHub Copilot Chat のセッション履歴
- 対象ディレクトリ：`chatSessions` 内の JSON ファイル

### 4.3 中間データの設計仕様

#### ① session-meta（定量データ）

生のログからプログラムで抽出・計算するメタデータ。

```json
{
  "session_id": "0ae1c6de-1ed4-41c3-9daa-5567cc87b0f7",
  "project_path": "c:\\Users\\...\\github\\ai-dev-skill-base",
  "start_time": "2026-04-05T13:04:15.018Z",
  "duration_minutes": 5,
  "user_message_count": 4,
  "assistant_message_count": 38,
  "tool_counts": {
    "Bash": 17,
    "Read": 6,
    "Glob": 3,
    "Write": 1
  },
  "languages": {
    "Markdown": 5,
    "JSON": 1,
    "Shell": 1
  },
  "git_commits": 1,
  "git_pushes": 1,
  "input_tokens": 6896,
  "output_tokens": 6082,
  "first_prompt": "作成されたタスクをもとに開発を進めていくスキルを作成したい",
  "user_response_times": [28.864, 28.864, 16.3],
  "tool_errors": 0,
  "lines_added": 187,
  "lines_removed": 0,
  "files_modified": 1,
  "message_hours": [22, 22, 22, 22]
}
```

#### ② facets（定性データ・特徴量）

会話内容や session-meta を LLM で解析・要約・分類した定性データ。

```json
{
  "session_id": "0ae1c6de-1ed4-41c3-9daa-5567cc87b0f7",
  "project_area": {
    "name": "Custom Skills Authoring",
    "description": "作成されたタスクをもとに開発を進めていくスキルの作成"
  },
  "primary_goal": "Create Skill",
  "session_type": "Multi Task",
  "inferred_satisfaction": "Likely Satisfied",
  "wins": [
    {
      "title": "スキルパイプラインの構築",
      "description": "タスク生成から開発までを一連のスキルとして機能させることに成功した。"
    }
  ],
  "frictions": [
    {
      "category": "Misunderstood Request",
      "detail": "ファイルの配置ディレクトリを間違える手戻りが発生した"
    }
  ],
  "suggested_rules": [
    {
      "rule_text": "スキルを作成する際は必ず `.agents/skills/` ディレクトリに配置すること",
      "reason": "ファイルの配置ミスによる手戻りを防ぐため"
    }
  ],
  "suggested_patterns": [
    {
      "title": "タスク着手前のブランチ作成",
      "description": "タスクに取り掛かる前に、developからブランチを作成する手順を明確化する。"
    }
  ]
}
```

### 4.4 ユーザーインターフェース

| 出力形式 | 詳細 |
|---|---|
| Copilot Chat パネル | Markdown（表・リスト等）による分析サマリの即時返答 |
| Webview（詳細レポート） | チャット内のリンク/ボタンから VS Code Webview を開き、HTML/CSS でグラフィカルなレポートをレンダリング |

### 4.5 提供形態

CLI 解析ツール ＋ Copilot Chat エージェント（または スキル）のハイブリッド構成

---

## 5. 用語定義

| 用語 | 定義 |
|---|---|
| session-meta | セッション単位の定量メタデータ（プログラムで算出） |
| facets | セッション単位の定性特徴量（LLM で生成） |
| chatSessions | VS Code ローカルストレージ内の Copilot Chat 履歴 JSON |
| .copilot-insights/ | 中間データの保存ディレクトリ（プロジェクト直下） |
