# Insights for GitHub Copilot

GitHub Copilot Chat のセッション履歴を分析し、利用傾向・改善提案を VS Code 上で確認できるツールです。

- **CLI ツール（Python）**: セッション JSONL を解析して定量メタデータと LLM による定性分析を生成します
- **VS Code 拡張機能（TypeScript）**: Copilot Chat パネルに `@insights` コマンドでサマリと HTML レポートを表示します

---

## 動作要件

| 項目 | バージョン |
|------|-----------|
| Python | 3.11 以上 |
| VS Code | 1.90.0 以上 |
| GitHub Copilot Chat | 有効化済み |
| Anthropic API キー | facets 生成に必要（`--skip-llm` で省略可） |

---

## セットアップ

### 1. CLI ツールのインストール

```bash
pip install -e .
```

### 2. Anthropic API キーの設定

```bash
# Windows (PowerShell)
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# macOS / Linux
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 3. VS Code 拡張機能のビルド（開発時）

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
Step 1: python -m copilot_insights   ← ここで AI 分析が走る
          │
          ▼
        .copilot-insights/ に分析結果を保存
          │
          ▼
Step 2: @insights /summary           ← 保存済み結果を表示
        @insights /report
```

### Step 1: CLI ツールで AI 分析を実行

分析したいワークスペースのディレクトリで実行します。VS Code の chatSessions を読み込み、**Anthropic API を呼び出して AI 分析**を行い、結果を `.copilot-insights/` に保存します。

```bash
# 基本実行（過去 30 日・最大 50 セッション）
python -m copilot_insights

# 過去 7 日間のみ対象
python -m copilot_insights --days 7

# LLM API を使わず既存データだけでサマリ生成（API キー不要）
python -m copilot_insights --skip-llm

# 分析するワークスペースを明示指定
python -m copilot_insights --workspace /path/to/your/project

# 全ワークスペースをまとめてスキャン
python -m copilot_insights --all-workspaces
```

実行すると `.copilot-insights/` ディレクトリに以下が生成されます。

```
.copilot-insights/
  session-meta/    # セッションごとの定量データ（JSON）
  facets/          # AI による定性分析（JSON）
```

### Step 2: VS Code 拡張機能で結果を表示

Step 1 の完了後、Copilot Chat を開いて以下のコマンドを入力します。

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

- 分析対象は **ローカルの** `%AppData%\Code\User\workspaceStorage\{id}\chatSessions\` のみです
- チャットの生テキストは外部に送信しません。LLM API へ送るのはセッションの**要約情報のみ**です
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
