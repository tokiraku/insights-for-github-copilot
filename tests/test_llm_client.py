# Unit tests for copilot_insights.llm_client module.
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from copilot_insights.llm_client import (
    AnthropicClient,
    FacetsGenerationError,
    _build_user_message,
    _parse_facets,
)
from copilot_insights.models import SCHEMA_VERSION, SessionMeta
from copilot_insights.parser import ParsedRequest, ParsedSession, ResponseChunk
from copilot_insights.writer import write_facets

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_BASE_META: SessionMeta = SessionMeta(
    schema_version=SCHEMA_VERSION,
    session_id="sess-test-001",
    start_time="2026-04-01T10:00:00.000Z",
    duration_minutes=30.0,
    user_message_count=5,
    tool_counts={"Read": 3, "Edit": 2},
    languages=["Python"],
    input_tokens=400,
    output_tokens=800,
    lines_added=50,
    lines_removed=10,
    files_modified=["src/foo.py"],
    tool_errors=0,
    user_response_times=[12.5, 8.0],
    message_hours=[10, 10, 10, 10, 10],
)

_VALID_LLM_JSON: dict[str, Any] = {
    "project_area": "backend API",
    "primary_goal": "Implement a new REST endpoint",
    "session_type": "feature_development",
    "inferred_satisfaction": "high",
    "wins": ["Endpoint implemented successfully"],
    "frictions": ["Test setup took longer than expected"],
    "suggested_rules": ["Always write tests before implementing new endpoints"],
    "suggested_patterns": ["Use dependency injection for service classes"],
}


def _make_mock_response(
    text: str,
    input_tokens: int = 100,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    output_tokens: int = 200,
) -> MagicMock:
    """Build a mock anthropic.types.Message with a single text block and usage."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.cache_creation_input_tokens = cache_creation_tokens
    usage.cache_read_input_tokens = cache_read_tokens
    usage.output_tokens = output_tokens
    response = MagicMock()
    response.content = [block]
    response.usage = usage
    return response


# ---------------------------------------------------------------------------
# AnthropicClient initialisation
# ---------------------------------------------------------------------------


def test_init_raises_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """AnthropicClient.__init__ は ANTHROPIC_API_KEY 未設定時に EnvironmentError を raise する。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
        AnthropicClient()


def test_init_succeeds_when_api_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """ANTHROPIC_API_KEY が設定されているとき、AnthropicClient が正常に初期化される。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-12345")
    with patch("anthropic.Anthropic"):
        client = AnthropicClient()
    assert client is not None


# ---------------------------------------------------------------------------
# generate_facets — happy path
# ---------------------------------------------------------------------------


def test_generate_facets_returns_valid_facets(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常な LLM レスポンスから Facets 型が返される。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_response = _make_mock_response(json.dumps(_VALID_LLM_JSON))

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_messages = MagicMock()
        mock_messages.create.return_value = mock_response
        mock_anthropic_cls.return_value.messages = mock_messages

        client = AnthropicClient()
        facets = client.generate_facets(_BASE_META, "Short summary of the session.")

    assert facets["schema_version"] == SCHEMA_VERSION
    assert facets["session_id"] == "sess-test-001"
    assert facets["project_area"] == "backend API"
    assert facets["session_type"] == "feature_development"
    assert facets["inferred_satisfaction"] == "high"
    assert isinstance(facets["wins"], list)
    assert isinstance(facets["frictions"], list)
    assert isinstance(facets["suggested_rules"], list)
    assert isinstance(facets["suggested_patterns"], list)


def test_generate_facets_strips_markdown_fences(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM がコードフェンス付きで JSON を返した場合も正しく解析される。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    fenced = f"```json\n{json.dumps(_VALID_LLM_JSON)}\n```"
    mock_response = _make_mock_response(fenced)

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_messages = MagicMock()
        mock_messages.create.return_value = mock_response
        mock_anthropic_cls.return_value.messages = mock_messages

        client = AnthropicClient()
        facets = client.generate_facets(_BASE_META, "Summary")

    assert facets["project_area"] == "backend API"


# ---------------------------------------------------------------------------
# generate_facets — error paths
# ---------------------------------------------------------------------------


def test_generate_facets_raises_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM が不正な JSON を返したとき FacetsGenerationError を raise する。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_response = _make_mock_response("This is not JSON at all.")

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_messages = MagicMock()
        mock_messages.create.return_value = mock_response
        mock_anthropic_cls.return_value.messages = mock_messages

        client = AnthropicClient()
        with pytest.raises(FacetsGenerationError, match="not valid JSON"):
            client.generate_facets(_BASE_META, "Summary")


def test_generate_facets_raises_on_missing_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """必須キーが欠けた JSON を LLM が返したとき FacetsGenerationError を raise する。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    incomplete = {"project_area": "backend", "primary_goal": "test"}
    mock_response = _make_mock_response(json.dumps(incomplete))

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_messages = MagicMock()
        mock_messages.create.return_value = mock_response
        mock_anthropic_cls.return_value.messages = mock_messages

        client = AnthropicClient()
        with pytest.raises(FacetsGenerationError, match="missing required keys"):
            client.generate_facets(_BASE_META, "Summary")


def test_generate_facets_raises_when_no_text_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM レスポンスにテキストブロックがない場合 FacetsGenerationError を raise する。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    empty_block = MagicMock()
    empty_block.type = "tool_use"  # not "text"
    mock_response = MagicMock()
    mock_response.content = [empty_block]

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_messages = MagicMock()
        mock_messages.create.return_value = mock_response
        mock_anthropic_cls.return_value.messages = mock_messages

        client = AnthropicClient()
        with pytest.raises(FacetsGenerationError, match="no text content"):
            client.generate_facets(_BASE_META, "Summary")


# ---------------------------------------------------------------------------
# _parse_facets — unit tests
# ---------------------------------------------------------------------------


def test_parse_facets_adds_schema_version() -> None:
    """_parse_facets は schema_version と session_id を正しく設定する。"""
    raw = json.dumps(_VALID_LLM_JSON)
    facets = _parse_facets(raw, "my-session")
    assert facets["schema_version"] == SCHEMA_VERSION
    assert facets["session_id"] == "my-session"


def test_parse_facets_empty_lists_allowed() -> None:
    """wins / frictions / suggested_rules / suggested_patterns が空リストでも通る。"""
    data = {**_VALID_LLM_JSON, "wins": [], "frictions": [], "suggested_rules": [], "suggested_patterns": []}
    facets = _parse_facets(json.dumps(data), "s1")
    assert facets["wins"] == []
    assert facets["suggested_rules"] == []


# ---------------------------------------------------------------------------
# _build_user_message
# ---------------------------------------------------------------------------


def test_build_user_message_contains_session_id() -> None:
    """_build_user_message の出力に session_id が含まれる。"""
    msg = _build_user_message(_BASE_META, "Short summary")
    assert "sess-test-001" in msg


def test_build_user_message_contains_summary() -> None:
    """_build_user_message の出力に会話要約が含まれる。"""
    msg = _build_user_message(_BASE_META, "Short summary about testing")
    assert "Short summary about testing" in msg


def test_build_user_message_excludes_response_times() -> None:
    """_build_user_message は user_response_times を送信しない（不要なデータ削減）。"""
    msg = _build_user_message(_BASE_META, "summary")
    assert "user_response_times" not in msg


# ---------------------------------------------------------------------------
# FR-003-03: generate → write integration (facets file output)
# ---------------------------------------------------------------------------


class TestFacetsWriteIntegration:
    """generate_facets() の出力を write_facets() でディスクに書き出す統合テスト。"""

    def _make_client_with_mock(
        self,
        monkeypatch: pytest.MonkeyPatch,
        llm_json: dict,
    ) -> AnthropicClient:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_response = _make_mock_response(json.dumps(llm_json))
        self._mock_messages = MagicMock()
        self._mock_messages.create.return_value = mock_response
        self._patcher = patch("anthropic.Anthropic")
        mock_cls = self._patcher.start()
        mock_cls.return_value.messages = self._mock_messages
        return AnthropicClient()

    def teardown_method(self) -> None:
        if hasattr(self, "_patcher"):
            self._patcher.stop()

    def test_generated_facets_written_to_correct_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """generate_facets() の結果を write_facets() で書き出すと正しいパスにファイルが作られる。"""
        client = self._make_client_with_mock(monkeypatch, _VALID_LLM_JSON)
        facets = client.generate_facets(_BASE_META, "summary")
        dest = write_facets(tmp_path, facets)

        assert dest == tmp_path / "facets" / "sess-test-001.json"
        assert dest.exists()

    def test_written_file_contains_schema_version(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """書き出された JSON に schema_version フィールドが含まれる（NFR-004）。"""
        client = self._make_client_with_mock(monkeypatch, _VALID_LLM_JSON)
        facets = client.generate_facets(_BASE_META, "summary")
        dest = write_facets(tmp_path, facets)

        data = json.loads(dest.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION

    def test_written_file_contains_all_required_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """書き出された JSON が Facets の全フィールドを含む。"""
        client = self._make_client_with_mock(monkeypatch, _VALID_LLM_JSON)
        facets = client.generate_facets(_BASE_META, "summary")
        dest = write_facets(tmp_path, facets)

        data = json.loads(dest.read_text(encoding="utf-8"))
        required_keys = {
            "schema_version",
            "session_id",
            "project_area",
            "primary_goal",
            "session_type",
            "inferred_satisfaction",
            "wins",
            "frictions",
            "suggested_rules",
            "suggested_patterns",
        }
        assert required_keys.issubset(data.keys())

    def test_generate_facets_from_session_writes_correctly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """generate_facets_from_session() → write_facets() のエンドツーエンドフローが動作する。"""
        session = ParsedSession(
            session_id="e2e-session",
            creation_date="2026-04-01T10:00:00.000Z",
            selected_model="gpt-4o",
            requests=[
                ParsedRequest(
                    request_id="r1",
                    timestamp="2026-04-01T10:00:00.000Z",
                    agent="copilot",
                    model_id="gpt-4o",
                    message_text="Help me fix the bug",
                    response_text="Sure, here is the fix",
                    response_chunks=[ResponseChunk(value="Sure, here is the fix", kind="")],
                    time_spent_waiting=0.0,
                )
            ],
        )
        meta: SessionMeta = SessionMeta(
            **{**_BASE_META, "session_id": "e2e-session"}
        )

        client = self._make_client_with_mock(monkeypatch, _VALID_LLM_JSON)
        facets = client.generate_facets_from_session(session, meta)
        dest = write_facets(tmp_path, facets)

        data = json.loads(dest.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION
        assert data["session_id"] == "e2e-session"
        assert dest == tmp_path / "facets" / "e2e-session.json"


# ---------------------------------------------------------------------------
# NFR-005: usage accumulation and log_usage_summary
# ---------------------------------------------------------------------------


class TestUsageAccumulation:
    def _make_client(self, monkeypatch: pytest.MonkeyPatch) -> AnthropicClient:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.Anthropic"):
            return AnthropicClient()

    def test_initial_counters_are_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._make_client(monkeypatch)
        assert client._total_input_tokens == 0
        assert client._total_cache_creation_tokens == 0
        assert client._total_cache_read_tokens == 0
        assert client._total_output_tokens == 0
        assert client._call_count == 0

    def test_accumulate_usage_increments_counters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._make_client(monkeypatch)
        mock_resp = _make_mock_response(
            json.dumps(_VALID_LLM_JSON),
            input_tokens=50,
            cache_creation_tokens=200,
            cache_read_tokens=0,
            output_tokens=100,
        )
        client._accumulate_usage(mock_resp)

        assert client._total_input_tokens == 50
        assert client._total_cache_creation_tokens == 200
        assert client._total_output_tokens == 100
        assert client._call_count == 1

    def test_accumulate_usage_sums_across_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._make_client(monkeypatch)
        resp1 = _make_mock_response("", input_tokens=100, cache_read_tokens=50, output_tokens=80)
        resp2 = _make_mock_response("", input_tokens=20, cache_read_tokens=300, output_tokens=60)
        client._accumulate_usage(resp1)
        client._accumulate_usage(resp2)

        assert client._total_input_tokens == 120
        assert client._total_cache_read_tokens == 350
        assert client._total_output_tokens == 140
        assert client._call_count == 2

    def test_log_usage_summary_does_nothing_when_no_calls(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        client = self._make_client(monkeypatch)
        client.log_usage_summary()
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_log_usage_summary_prints_after_calls(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        client = self._make_client(monkeypatch)
        resp = _make_mock_response(
            "", input_tokens=100, cache_creation_tokens=500, cache_read_tokens=200, output_tokens=150
        )
        client._accumulate_usage(resp)
        client.log_usage_summary()

        out = capsys.readouterr().out
        assert "LLM usage summary" in out
        assert "Cache hit rate" in out
        assert "Estimated cost" in out

    def test_log_usage_summary_shows_correct_cache_hit_rate(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Cache hit rate = cache_read / (input + cache_write + cache_read)."""
        client = self._make_client(monkeypatch)
        # 200 cache_read out of 200+0+200 = 400 total → 50%
        resp = _make_mock_response("", input_tokens=200, cache_read_tokens=200, output_tokens=0)
        client._accumulate_usage(resp)
        client.log_usage_summary()

        out = capsys.readouterr().out
        assert "50.0%" in out

    def test_generate_facets_increments_call_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        mock_response = _make_mock_response(json.dumps(_VALID_LLM_JSON))

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = mock_response
            client = AnthropicClient()
            client.generate_facets(_BASE_META, "summary")

        assert client._call_count == 1
