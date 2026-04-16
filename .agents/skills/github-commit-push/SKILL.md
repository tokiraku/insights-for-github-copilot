---
name: github-commit-push
description: 'GitHubコミット・プッシュ支援スキル。変更差分を分析してコミットメッセージを自動提案し、ユーザー承認後にコミット・プッシュを実行する。Use when: commit, push, コミット, プッシュ, git commit, git push, コミットメッセージ, commit message'
argument-hint: 'コミットメッセージのヒント or ブランチ名（省略可）'
---

# GitHubコミット・プッシュ支援スキル

## 概要

ローカルの変更を分析してコミットメッセージを自動提案し、ユーザーの承認を得てからコミット・プッシュを実行する。
GitHub MCPが利用可能な場合はMCP経由の操作を優先する。

---

## 実行手順

### Step 1: 変更差分の収集

以下のコマンドで現在の変更状況を把握する。

```bash
git status
git diff --stat
git diff --cached --stat
```

- `git diff HEAD` でコミット対象の全差分を確認する
- 未ステージのファイルがある場合は、ユーザーに「すべてステージするか、特定ファイルのみか」を確認する

### Step 2: コミットメッセージの生成

差分の内容を分析し、以下のルールに従ってコミットメッセージを生成する。

#### メッセージ形式（Conventional Commits 準拠）

```
<type>(<scope>): <subject>

<body> ※必要な場合のみ

<footer> ※Breaking Change や Issue 参照がある場合のみ
```

#### type の選定基準

| type | 使用場面 |
|------|----------|
| `feat` | 新機能の追加 |
| `fix` | バグ修正 |
| `docs` | ドキュメントのみの変更 |
| `style` | コードの意味に影響しない変更（フォーマット等） |
| `refactor` | バグ修正・機能追加を伴わないコード変更 |
| `test` | テストの追加・修正 |
| `chore` | ビルドプロセス・ツール・設定変更 |
| `ci` | CI/CD 設定の変更 |
| `perf` | パフォーマンス改善 |
| `revert` | 以前のコミットの取り消し |

#### メッセージ生成ルール

- `subject` は **50文字以内**、命令形で記述（"Add feature" / "機能を追加"）
- 変更ファイルが複数カテゴリにまたがる場合は、最も影響の大きい type を選ぶ
- 引数でヒントが渡された場合は、その内容を優先して反映する
- Breaking Change がある場合は `!` を type 後に付与し、footer に `BREAKING CHANGE:` を記述する

### Step 3: プッシュ先の確認

```bash
git branch --show-current
git remote -v
```

- 現在のブランチとリモートリポジトリ（origin）を確認する
- `main` / `master` への直接プッシュの場合は **警告を表示**して確認を強調する

### Step 4: ユーザーへの承認確認

以下の情報をまとめてユーザーに提示し、**明示的な承認を得てから**コミット・プッシュを実行する。

## 実行予定の操作

**変更ファイル:**
<ファイル一覧と変更種別（A/M/D）>

**提案コミットメッセージ:**
```
<type>(<scope>): <subject>

<body>
```

**プッシュ先:**
- リモート: origin
- ブランチ: <branch-name>
- URL: <remote-url>

⚠️ **注意:** main/master への直接プッシュの場合はここに警告を追加

承認しますか？ [変更点があれば指示してください]

ユーザーが修正を要求した場合は、コミットメッセージを修正して再度提示する。

### Step 5: コミット・プッシュの実行

ユーザーが承認したら以下を実行する。

#### GitHub MCP が利用可能な場合（優先）

> **MCP利用判定:** 環境にGitHub MCPが設定されている場合（`mcp_github_*` ツールが利用可能な場合）はMCPを優先する。`mcp_github_*` ツールが見当たらない場合は、Claude Code の MCP 設定（`/mcp` コマンドまたは設定ファイル）で GitHub MCP サーバーを有効化するようユーザーに案内し、有効化を試みてから再確認する。それでも利用不可の場合はローカルのgitコマンドにフォールバックする。

1. `mcp_github_create_or_update_file` または該当MCPツールでコミット操作を行う
2. MCP経由でプッシュが完了したら、コミットURLをユーザーに提示する

#### ローカル git コマンドを使用する場合（フォールバック）

```bash
# 未ステージファイルがある場合（ユーザーが「すべてステージ」を選択した場合）
git add -A

# コミット（Conventional Commits形式）
git commit -m "$(cat <<'EOF'
<type>(<scope>): <subject>

<body>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"

# プッシュ
git push origin <branch-name>
```

### Step 6: 完了報告

コミット・プッシュが完了したら以下を報告する。

## 完了
```
- **コミットハッシュ**: <hash>
- **ブランチ**: <branch-name>
- **リモート**: <remote-url>
- **コミットメッセージ**: <message>

GitHub でコミットを確認: <commit-url>
```

GitHub MCP が利用可能な場合は `mcp_github_get_commit` でコミット情報を取得してURLを提示する。

---

## 注意事項

- **コミット・プッシュは必ずユーザー承認後に実行する** — 承認なしに実行しない
- `main` / `master` への直接プッシュは強調して警告する
- `.env` / シークレットファイルが変更に含まれる場合は **プッシュを中止**して警告する
- `--force` / `--no-verify` オプションはユーザーの明示的な指示がない限り使用しない
- `git add -A` や `git add .` は意図しないファイル（`.env`、大容量バイナリ）を含む可能性があるため、差分確認後にユーザーへ通知してから実行する
- GitHub MCP が利用可能かどうかを最初に確認し、可能な限りMCPを優先する
