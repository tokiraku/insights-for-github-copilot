# Insights for GitHub Copilot

GitHub Copilot Chat のセッション履歴を分析し、利用傾向・改善提案を VS Code 上で確認できるツールです。

- **CLI ツール（Python）**: セッション JSONL を解析して定量メタデータ（session-meta）を生成します
- **VS Code 拡張機能（TypeScript）**: vscode.lm API で session-meta から定性分析（facets）を自動生成し、Copilot Chat パネルに `@insights` コマンドでサマリと HTML レポートを表示します

---

## 動作要件

| 項目 | バージョン |
|------|-----------|
| Python | 3.11 以上 |
| VS Code | 1.90.0 以上 |
| GitHub Copilot Chat | 有効化済み |

> **API キー不要**: facets の生成は VS Code 拡張機能が vscode.lm API（GitHub Copilot）を通じて行うため、Anthropic API キーは不要です。

---

## セットアップ

### 1. CLI ツールのインストール

```bash
pip install -e .
```

### 2. VS Code 拡張機能のビルド（開発時）

```bash
cd extension
npm install
npm run compile
```

その後、VS Code の「拡張機能のデバッグ」（F5）で起動します。

---

## 使い方

全体の流れは以下の 2 ステップです。

```
Step 1: python -m copilot_insights   ← session-meta を生成
          │
          ▼
        .copilot-insights/session-meta/ に定量データを保存
          │
          ▼
Step 2: @insights /summary           ← 拡張機能が facets を自動生成してサマリを表示
        @insights /report
```

### Step 1: CLI ツールで session-meta を生成

分析したいワークスペースのディレクトリで実行します。VS Code の chatSessions を読み込み、セッションの定量メタデータを `.copilot-insights/session-meta/` に保存します。

```bash
# 基本実行（過去 30 日・最大 50 セッション）
python -m copilot_insights

# 過去 7 日間のみ対象
python -m copilot_insights --days 7

# 分析するワークスペースを明示指定
python -m copilot_insights --workspace /path/to/your/project

# 全ワークスペースをまとめてスキャン
python -m copilot_insights --all-workspaces
```

実行すると `.copilot-insights/session-meta/` にセッションごとの定量データが保存されます。

```
.copilot-insights/
  session-meta/    # セッションごとの定量データ（JSON）
  facets/          # AI による定性分析（JSON）← @insights 実行時に拡張機能が自動生成
```

### Step 2: VS Code 拡張機能で結果を表示

Step 1 の完了後、Copilot Chat を開いて以下のコマンドを入力します。facets がまだ生成されていないセッションは、vscode.lm API（GitHub Copilot）を使って自動的に生成されます。

| コマンド | 説明 |
|---------|------|
| `@insights /summary` | Markdown サマリをチャットパネルに表示 |
| `@insights /report` | 詳細 HTML レポートを Webview で表示 |

---

## 出力内容

### Markdown サマリ（`@insights /summary`）

- **Stats**: セッション数・メッセージ数・トークン数・変更行数
- **What You Work On**: プロジェクト領域の分布（上位 5 件）
- **Top Tools Used**: 使用ツールのランキング（上位 5 件）
- **Wins**: 達成した成果の一覧
- **Friction**: 発生した障害・課題の一覧
- **Suggested Rules for `copilot-instructions.md`**: 追記候補ルールの提案

### HTML レポート（`@insights /report`）

Webview パネルで上記サマリの詳細版を表示します。

---

## データとプライバシー

- 分析対象は **ローカルの** VS Code ユーザーデータ配下の `workspaceStorage/{id}/chatSessions/` のみです（Windows: `%AppData%\Code\User\`、macOS: `~/Library/Application Support/Code/`、Linux: `~/.config/Code/`）
- チャットの生テキストは外部に送信しません。vscode.lm API へ送るのはセッションの**要約情報のみ**です
- `.copilot-insights/` には個人的なセッション情報が含まれるため、`.gitignore` への追加を推奨します

```gitignore
.copilot-insights/
```

---

## 開発・テスト

```bash
# テスト実行（パフォーマンステスト除く）
python -m pytest --ignore=tests/test_performance.py -q

# パフォーマンステストのみ
python -m pytest tests/test_performance.py -v -s
```
