# タスクリスト: GitHub Copilot Insights 機能

作成日: 2026-04-16
元要件: docs/requirements/copilot-insights-requirements.md
技術スタック: Python（CLI） + Copilot スキル（フロントエンド）
ステータス: In Progress

---

## フェーズ1: 設計・準備

- [x] [SETUP-001] プロジェクト構造・パッケージ初期化（`pyproject.toml`, `ruff` 設定）
  - 優先度: Must Have
  - 関連要件: CON-001
  - 完了基準: `pip install -e .` が通る、`ruff check` がエラーなし

- [x] [SETUP-002] `.copilot-insights/` の git 追跡除外設定
  - 優先度: Must Have
  - 関連要件: CON-002, NFR-002
  - 完了基準: `.copilot-insights/` が git 追跡対象外になっている（ルート `.gitignore` に追加済み）

- [x] [SETUP-003] `schema_version` を含む session-meta / facets の Python 型定義ファイル作成（`TypedDict` または `dataclass`）
  - 優先度: Must Have
  - 関連要件: FR-002, FR-003, NFR-004
  - 完了基準: `SessionMeta` / `Facets` の型が定義され、`schema_version` フィールドを持つ

---

## フェーズ2: CLIツール — データ読み取り基盤（FR-001）

- [x] [FR-001-01] workspaceId 特定ロジックの実装
  - 優先度: Must Have
  - 関連要件: FR-001, CON-002
  - 完了基準: `state.vscdb` の `terminal.integrated.layoutInfo` を読み取り、現在のワークスペース ID が返る。特定不能な場合は全ワークスペースをスキャンするフォールバックが動く
  - メモ: `%AppData%\Code\User\workspaceStorage\{id}\state.vscdb` を SQLite で読む（標準ライブラリ `sqlite3` を使用）

- [x] [FR-001-02] chatSessions ディレクトリのスキャン・`.jsonl` ファイル列挙ロジックの実装
  - 優先度: Must Have
  - 関連要件: FR-001
  - 完了基準: 対象ワークスペースの `chatSessions/` 以下の `.jsonl` ファイル一覧が取得できる

- [x] [FR-001-03] JSONL パーサーの実装
  - 優先度: Must Have
  - 関連要件: FR-001, CON-002
  - 完了基準: `kind=0` からセッション初期化情報を、`kind=2` の最終スナップショットからリクエスト一覧を正しく抽出できる。`message.text` および `response[]` の `value` フィールドを取得できる
  - メモ: `k=["requests"]` の最後の行が確定データ。`k=["requests", N, "response"]` は差分追記

- [x] [FR-001-04] 30日フィルタ・最大50セッション上限の適用ロジック実装
  - 優先度: Must Have
  - 関連要件: FR-001, CON-005
  - 完了基準: `creationDate` が30日以内かつ最大50件のセッションのみが返る

- [x] [FR-001-test] JSONL パーサーのユニットテスト
  - 優先度: Must Have
  - 関連要件: FR-001
  - 完了基準: サンプル `.jsonl` ファイルを使ってセッション情報・メッセージ・レスポンスが正しく解析されることをテストが証明する

---

## フェーズ3: CLIツール — session-meta 抽出（FR-002）

- [x] [FR-002-01] session-meta 抽出ロジックの実装
  - 優先度: Must Have
  - 関連要件: FR-002
  - 完了基準: パース済みセッションから以下が算出される：`session_id`, `start_time`, `duration_minutes`, `user_message_count`, `tool_counts`, `languages`, `input_tokens`, `output_tokens`, `lines_added`, `lines_removed`, `files_modified`, `tool_errors`, `user_response_times`, `message_hours`

- [x] [FR-002-02] `.copilot-insights/session-meta/{session_id}.json` への書き出しロジック実装
  - 優先度: Must Have
  - 関連要件: FR-002, NFR-004
  - 完了基準: 出力 JSON に `schema_version` フィールドが含まれる。ディレクトリが存在しない場合は自動生成される

- [x] [FR-002-test] session-meta 抽出のユニットテスト
  - 優先度: Must Have
  - 関連要件: FR-002
  - 完了基準: 各フィールドの算出値が期待値と一致することをテストが証明する

---

## フェーズ4: CLIツール — facets 生成（FR-003）

- [x] [FR-003-01] LLM API クライアントの実装（Anthropic Claude）
  - 優先度: Must Have
  - 関連要件: FR-003, NFR-003, CON-003
  - 完了基準: 環境変数 `ANTHROPIC_API_KEY` から読み込み API 呼び出しができる。キーが未設定の場合は明示的なエラーを返す
  - メモ: `anthropic` PyPI パッケージを使用。プロンプトキャッシュ（NFR-005）を考慮した実装

- [x] [FR-003-02] facets 生成プロンプトの設計・実装
  - 優先度: Must Have
  - 関連要件: FR-003, NFR-002
  - 完了基準: `project_area`, `primary_goal`, `session_type`, `inferred_satisfaction`, `wins`, `frictions`, `suggested_rules`, `suggested_patterns` を含む JSON を LLM が出力する。生の会話全文を送信しない（要約のみ送信）

- [x] [FR-003-03] `.copilot-insights/facets/{session_id}.json` への書き出しロジック実装
  - 優先度: Must Have
  - 関連要件: FR-003, NFR-004
  - 完了基準: 出力 JSON に `schema_version` フィールドが含まれる

- [x] [FR-003-test] facets 生成の統合テスト（LLM モック使用）
  - 優先度: Must Have
  - 関連要件: FR-003
  - 完了基準: モック LLM レスポンスを使い、出力スキーマが `Facets` 型に適合することをテストが証明する

---

## フェーズ5: CLIツール — エントリポイント（NFR-001）

- [x] [INFRA-001] CLI エントリポイント実装（引数パース）
  - 優先度: Must Have
  - 関連要件: NFR-001, NFR-006, FR-008
  - 完了基準: `--days N`, `--skip-llm`, `--all-workspaces`, `--workspace <path>` オプションが動作する

- [x] [INFRA-002] パイプライン全体の統合（FR-001 → FR-002 → FR-003 の順次実行）
  - 優先度: Must Have
  - 関連要件: FR-001, FR-002, FR-003
  - 完了基準: `python -m copilot_insights` で一連の処理が完了し、`.copilot-insights/` に中間データが出力される

- [x] [NFR-001-test] パフォーマンス計測スクリプトの作成
  - 優先度: Must Have
  - 関連要件: NFR-001
  - 完了基準: 50セッション分の session-meta 抽出が LLM 呼び出し除いて60秒以内に完了することを確認できる

---

## フェーズ6: Copilot スキル — サマリ返答（FR-004）

- [x] [FR-004-01] SKILL.md の作成（insightsスキルのエントリポイント定義）
  - 優先度: Must Have
  - 関連要件: FR-004, CON-001
  - 完了基準: Copilot Chat で `@insights` または指定コマンドが認識される

- [x] [FR-004-02] `.copilot-insights/` の中間データ読み込みロジック実装（スキル内）
  - 優先度: Must Have
  - 関連要件: FR-004
  - 完了基準: session-meta と facets の JSON を読み込み、集計値が正しく返る

- [x] [FR-004-03] Markdown サマリ生成ロジック実装
  - 優先度: Must Have
  - 関連要件: FR-004
  - 完了基準: 全体統計・利用傾向・Wins・Friction・改善提案の5セクションを含む Markdown が Chat パネルに返答される

- [x] [FR-004-04] Webview 起動リンクのサマリへの埋め込み
  - 優先度: Must Have
  - 関連要件: FR-004, FR-005
  - 完了基準: サマリ末尾に「詳細レポートを表示」リンクが表示され、クリックで Webview が起動する

---

## フェーズ7: Webview — HTML レポート（FR-005）

- [x] [FR-005-01] VS Code Webview パネルの実装
  - 優先度: Must Have
  - 関連要件: FR-005, CON-001
  - 完了基準: スキルからのトリガーで Webview パネルが開き、中間データを受け取れる

- [x] [FR-005-02] HTML レポートテンプレート実装（全セクション）
  - 優先度: Must Have
  - 関連要件: FR-005
  - 完了基準: Stats・What You Work On・Top Tools Used・Languages・Wins・Friction・改善提案の各セクションが表示される

- [x] [FR-005-03] CSS スタイリング（VS Code テーマカラー変数対応）
  - 優先度: Must Have
  - 関連要件: FR-005
  - 完了基準: ライト/ダークテーマ両方で視認性が確保されている

---

## フェーズ8: Should Have 対応

- [x] [FR-006-01] `--all-workspaces` モード実装（全ワークスペーススキャン）
  - 優先度: Should Have
  - 関連要件: FR-006
  - 完了基準: `--all-workspaces` 指定時に全ワークスペースの chatSessions を対象に分析が走る

- [x] [FR-007-01] `suggested_rules` のサマリ内強調表示実装
  - 優先度: Should Have
  - 関連要件: FR-007
  - 完了基準: `copilot-instructions.md` に追記すべきルール候補が専用セクションで表示される

- [x] [FR-008-01] `--days N` オプション実装
  - 優先度: Should Have
  - 関連要件: FR-008
  - 完了基準: `--days 7` 指定で直近7日のセッションのみが対象になる（FR-001-04 の拡張）

- [x] [NFR-005-01] Anthropic プロンプトキャッシュの実装・コスト計測
  - 優先度: Should Have
  - 関連要件: NFR-005
  - 完了基準: キャッシュヒット率をログ出力し、50セッション分の facets 生成コストが $1.00 USD 未満であることを確認

- [x] [NFR-006-01] `--skip-llm` オプション実装
  - 優先度: Should Have
  - 関連要件: NFR-006
  - 完了基準: `--skip-llm` 指定時に LLM API を呼ばず、既存の facets JSON のみでサマリが生成される

---

## フェーズ9: vscode.lm API — 拡張機能側新規実装

- [x] [LLM-001] `extension/src/models.ts` に `SessionSummary` 型を追加（vscode.lm への入力用）
  - 優先度: Must Have
  - 関連要件: FR-003
  - 完了基準: session-meta を要約した型が定義され、facetsGenerator で使用される

- [x] [LLM-002] `extension/src/facetsGenerator.ts` を新規作成（vscode.lm API で session-meta → facets を生成）
  - 優先度: Must Have
  - 関連要件: FR-003, NFR-003
  - 完了基準: `vscode.lm.selectChatModels()` で Copilot モデルを取得し、session-meta JSON を入力として facets JSON を生成できる

- [x] [LLM-003] `extension/src/dataLoader.ts` を修正（facets 未生成でも session-meta だけで動けるようエラー処理を調整）
  - 優先度: Must Have
  - 関連要件: FR-004
  - 完了基準: facets ディレクトリが存在しない場合でも session-meta のみで AggregatedInsights を返せる

- [x] [LLM-004] `extension/src/extension.ts` を修正（`/summary` 実行時に facets 未生成なら facetsGenerator を呼ぶ）
  - 優先度: Must Have
  - 関連要件: FR-004
  - 完了基準: `@insights /summary` 実行時に facets が存在しない場合は vscode.lm で生成してからサマリを返す

---

## フェーズ10: Python CLI — Anthropic 依存の削除

- [x] [LLM-005] `src/copilot_insights/__main__.py` から Anthropic 関連コードを削除（facets 生成ステップ・`--skip-llm` オプション削除）
  - 優先度: Must Have
  - 関連要件: NFR-003
  - 完了基準: `python -m copilot_insights` が session-meta 生成のみを行い、Anthropic 依存なしで動く

- [x] [LLM-006] `src/copilot_insights/llm_client.py` と `summarizer.py` を削除
  - 優先度: Must Have
  - 関連要件: NFR-003
  - 完了基準: 2ファイルが削除され、他モジュールからの参照がなくなっている

- [x] [LLM-007] `pyproject.toml` から `anthropic` 依存を削除
  - 優先度: Must Have
  - 関連要件: NFR-003
  - 完了基準: `pip install -e .` が `anthropic` なしで通る

---

## フェーズ11: テスト修正・ドキュメント更新

- [x] [LLM-008] Python テスト群から `test_llm_client.py` を削除し、影響を受けるテストを修正
  - 優先度: Must Have
  - 関連要件: FR-003
  - 完了基準: `python -m pytest --ignore=tests/test_performance.py -q` が全件パス

- [x] [LLM-009] `README.md` を更新（API キー不要・フロー変更の反映）
  - 優先度: Must Have
  - 関連要件: -
  - 完了基準: セットアップ手順・使い方セクションが新フローを正しく説明している

---

---

## フェーズ12: Node.js セットアップ & 拡張機能ビルド

- [ ] [NODE-001] Node.js LTS（v22 以上）をインストール ※ユーザー作業
  - 完了基準: `node --version` で v22.x.x 以上が表示される
  - 手順: https://nodejs.org から LTS 版をダウンロード → インストーラー実行 → VS Code 再起動

- [x] [NODE-002] `extension/.nvmrc` を追加（Node 22 を固定）
  - 完了基準: `extension/.nvmrc` に `22` が記載されている

- [x] [NODE-003] `extension/package.json` に `engines.node` フィールドを追加
  - 完了基準: `"node": ">=22.0.0"` が engines に含まれている

- [x] [NODE-004] README.md にセットアップ手順 Step 0（Node.js インストール）を追記
  - 完了基準: 動作要件テーブルに Node.js 行が追加され、セットアップ手順に Step 0 が存在する

- [ ] [NODE-005] `npm install` を実行して依存関係をインストール ※ユーザー作業
  - 完了基準: `extension/node_modules/` が生成される
  - 手順: VS Code ターミナルで `cd extension && npm install`

- [ ] [NODE-006] `npm run compile` を実行してビルド ※ユーザー作業
  - 完了基準: `extension/out/extension.js` が生成される
  - 手順: `npm run compile`

- [ ] [NODE-007] F5 で Extension Development Host を起動し `@insights` を確認 ※ユーザー作業
  - 完了基準: 新しい VS Code ウィンドウの Copilot Chat で `@insights /summary` が応答する

---

## 進捗サマリー

| フェーズ | 完了 | 総数 |
|----------|------|------|
| フェーズ1: 設計・準備 | 3 | 3 |
| フェーズ2: データ読み取り基盤 | 5 | 5 |
| フェーズ3: session-meta 抽出 | 3 | 3 |
| フェーズ4: facets 生成 | 4 | 4 |
| フェーズ5: CLI エントリポイント | 3 | 3 |
| フェーズ6: Copilot スキル | 4 | 4 |
| フェーズ7: Webview | 3 | 3 |
| フェーズ8: Should Have 対応 | 5 | 5 |
| フェーズ9: vscode.lm API — 拡張機能側新規実装 | 4 | 4 |
| フェーズ10: Python CLI — Anthropic 依存の削除 | 3 | 3 |
| フェーズ11: テスト修正・ドキュメント更新 | 2 | 2 |
| **合計** | **32** | **39** |
