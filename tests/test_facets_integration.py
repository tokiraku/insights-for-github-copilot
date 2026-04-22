# Integration tests for the FR-003 facets generation pipeline.
# Covers: ParsedSession → summarize → generate (mocked LLM) → write → schema validation.
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from copilot_insights.llm_client import AnthropicClient, FacetsGenerationError
from copilot_insights.models import SCHEMA_VERSION, Facets, SessionMeta
from copilot_insights.parser import ParsedRequest, ParsedSession, ResponseChunk
from copilot_insights.summarizer import summarize_session
from copilot_insights.writer import write_facets

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_VALID_LLM_RESPONSE: dict[str, Any] = {
    "project_area": "backend API",
    "primary_goal": "Implement REST endpoint for user management",
    "session_type": "feature_development",
    "inferred_satisfaction": "high",
    "wins": ["Endpoint implemented and tested", "Type safety improved"],
    "frictions": ["DB migration took longer than expected"],
    "suggested_rules": ["Always add integration tests for new endpoints"],
    "suggested_patterns": ["Use repository pattern for data access"],
}

_BASE_META: SessionMeta = SessionMeta(
    schema_version=SCHEMA_VERSION,
    session_id="integration-sess-001",
    start_time="2026-04-01T10:00:00.000Z",
    duration_minutes=45.0,
    user_message_count=8,
    tool_counts={"Read": 5, "Edit": 3, "Bash": 2},
    languages=["Python", "SQL"],
    input_tokens=600,
    output_tokens=1200,
    lines_added=80,
    lines_removed=20,
    files_modified=["src/api/users.py", "tests/test_users.py"],
    tool_errors=0,
    user_response_times=[15.0, 10.5, 8.0],
    message_hours=[10, 10, 10, 11, 11, 11, 11, 11],
)


def _make_session(
    session_id: str = "integration-sess-001",
    messages: list[tuple[str, str]] | None = None,
) -> ParsedSession:
    """Build a ParsedSession with the given (user_msg, assistant_resp) pairs."""
    if messages is None:
        messages = [
            ("Help me implement a REST endpoint", "Sure, let me create the endpoint"),
            ("Add input validation", "I'll add validation using Pydantic"),
            ("Write tests for it", "Here are the tests"),
        ]
    requests = [
        ParsedRequest(
            request_id=f"r{i}",
            timestamp="2026-04-01T10:00:00.000Z",
            agent="copilot",
            model_id="gpt-4o",
            message_text=user_msg,
            response_text=resp,
            response_chunks=[ResponseChunk(value=resp, kind="")],
            time_spent_waiting=0.0,
        )
        for i, (user_msg, resp) in enumerate(messages, start=1)
    ]
    return ParsedSession(
        session_id=session_id,
        creation_date="2026-04-01T10:00:00.000Z",
        selected_model="gpt-4o",
        requests=requests,
    )


def _make_mock_client(
    monkeypatch: pytest.MonkeyPatch,
    llm_json: dict[str, Any],
) -> AnthropicClient:
    """Build an AnthropicClient whose LLM call always returns *llm_json*."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-integration")
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(llm_json)
    mock_response = MagicMock()
    mock_response.content = [block]
    mock_messages = MagicMock()
    mock_messages.create.return_value = mock_response
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages = mock_messages
        client = AnthropicClient()
    # Patch the internal client so subsequent calls also use the mock
    client._client.messages = mock_messages  # noqa: SLF001
    return client


# ---------------------------------------------------------------------------
# End-to-end pipeline: session → summarize → generate → write → validate
# ---------------------------------------------------------------------------


class TestFacetsPipelineEndToEnd:
    """FR-003 フルパイプラインの統合テスト。"""

    def test_full_pipeline_produces_valid_facets_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """ParsedSession → summarize → generate → write の一連フローで有効な Facets JSON が生成される。"""
        session = _make_session()
        client = _make_mock_client(monkeypatch, _VALID_LLM_RESPONSE)

        # Step 1: summarize (must not include full text)
        summary = summarize_session(session)
        assert len(summary) > 0
        assert "Help me implement a REST endpoint" in summary  # user msg excerpt included
        assert len(summary) <= 1500  # NFR-002: within char limit

        # Step 2: generate facets via mocked LLM
        facets = client.generate_facets(_BASE_META, summary)

        # Step 3: write to disk
        dest = write_facets(tmp_path, facets)

        # Step 4: read back and validate schema
        data = json.loads(dest.read_text(encoding="utf-8"))
        _assert_facets_schema(data, expected_session_id="integration-sess-001")

    def test_generate_facets_from_session_full_pipeline(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """generate_facets_from_session() を使ったショートカットフローでも同じ結果が得られる。"""
        session = _make_session()
        client = _make_mock_client(monkeypatch, _VALID_LLM_RESPONSE)

        facets = client.generate_facets_from_session(session, _BASE_META)
        dest = write_facets(tmp_path, facets)

        data = json.loads(dest.read_text(encoding="utf-8"))
        _assert_facets_schema(data, expected_session_id="integration-sess-001")

    def test_output_file_path_matches_session_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """書き出し先のファイルパスが .copilot-insights/facets/{session_id}.json になる。"""
        session = _make_session(session_id="my-session-xyz")
        meta: SessionMeta = SessionMeta(**{**_BASE_META, "session_id": "my-session-xyz"})
        client = _make_mock_client(monkeypatch, _VALID_LLM_RESPONSE)

        facets = client.generate_facets_from_session(session, meta)
        dest = write_facets(tmp_path, facets)

        assert dest == tmp_path / "facets" / "my-session-xyz.json"


# ---------------------------------------------------------------------------
# Schema validation: Facets TypedDict conformance
# ---------------------------------------------------------------------------


class TestFacetsSchemaConformance:
    """生成された Facets が TypedDict の型制約を満たすことを確認する。"""

    def test_all_required_string_fields_are_strings(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """文字列フィールドがすべて str 型である。"""
        client = _make_mock_client(monkeypatch, _VALID_LLM_RESPONSE)
        facets = client.generate_facets(_BASE_META, "summary")

        assert isinstance(facets["schema_version"], str)
        assert isinstance(facets["session_id"], str)
        assert isinstance(facets["project_area"], str)
        assert isinstance(facets["primary_goal"], str)
        assert isinstance(facets["session_type"], str)
        assert isinstance(facets["inferred_satisfaction"], str)

    def test_all_list_fields_are_lists_of_strings(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """リストフィールドがすべて list[str] 型である。"""
        client = _make_mock_client(monkeypatch, _VALID_LLM_RESPONSE)
        facets = client.generate_facets(_BASE_META, "summary")

        for field in ("wins", "frictions", "suggested_rules", "suggested_patterns"):
            assert isinstance(facets[field], list), f"{field} should be a list"
            for item in facets[field]:
                assert isinstance(item, str), f"{field} items should be strings"

    def test_schema_version_matches_constant(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """schema_version が models.SCHEMA_VERSION と一致する。"""
        client = _make_mock_client(monkeypatch, _VALID_LLM_RESPONSE)
        facets = client.generate_facets(_BASE_META, "summary")
        assert facets["schema_version"] == SCHEMA_VERSION

    def test_empty_list_fields_are_valid(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """wins / frictions / suggested_rules / suggested_patterns が空リストでも有効。"""
        llm_resp = {
            **_VALID_LLM_RESPONSE,
            "wins": [],
            "frictions": [],
            "suggested_rules": [],
            "suggested_patterns": [],
        }
        client = _make_mock_client(monkeypatch, llm_resp)
        facets = client.generate_facets(_BASE_META, "summary")

        assert facets["wins"] == []
        assert facets["frictions"] == []
        assert facets["suggested_rules"] == []
        assert facets["suggested_patterns"] == []

    def test_written_json_round_trips_to_facets(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """ディスクに書き出した JSON を読み返すと Facets 型として扱える。"""
        client = _make_mock_client(monkeypatch, _VALID_LLM_RESPONSE)
        facets = client.generate_facets(_BASE_META, "summary")
        dest = write_facets(tmp_path, facets)

        raw = json.loads(dest.read_text(encoding="utf-8"))
        # Construct a Facets from the raw JSON to confirm all keys are present
        reloaded: Facets = Facets(
            schema_version=raw["schema_version"],
            session_id=raw["session_id"],
            project_area=raw["project_area"],
            primary_goal=raw["primary_goal"],
            session_type=raw["session_type"],
            inferred_satisfaction=raw["inferred_satisfaction"],
            wins=raw["wins"],
            frictions=raw["frictions"],
            suggested_rules=raw["suggested_rules"],
            suggested_patterns=raw["suggested_patterns"],
        )
        assert reloaded["session_id"] == "integration-sess-001"


# ---------------------------------------------------------------------------
# Multiple sessions
# ---------------------------------------------------------------------------


class TestMultipleSessionsProcessing:
    """複数セッションを連続処理したとき全ファイルが正しく書き出される。"""

    def test_multiple_sessions_produce_separate_files(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """3セッション処理すると facets/ に3つの JSON ファイルが生成される。"""
        session_ids = ["sess-a", "sess-b", "sess-c"]
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        for sid in session_ids:
            session = _make_session(session_id=sid)
            meta: SessionMeta = SessionMeta(**{**_BASE_META, "session_id": sid})
            client = _make_mock_client(monkeypatch, _VALID_LLM_RESPONSE)
            facets = client.generate_facets_from_session(session, meta)
            write_facets(tmp_path, facets)

        written = list((tmp_path / "facets").glob("*.json"))
        assert len(written) == 3
        written_names = {f.name for f in written}
        assert written_names == {"sess-a.json", "sess-b.json", "sess-c.json"}

    def test_each_file_has_correct_session_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        """各ファイルの session_id フィールドが対応するセッションのものと一致する。"""
        for sid in ("alpha", "beta"):
            session = _make_session(session_id=sid)
            meta: SessionMeta = SessionMeta(**{**_BASE_META, "session_id": sid})
            client = _make_mock_client(monkeypatch, _VALID_LLM_RESPONSE)
            facets = client.generate_facets_from_session(session, meta)
            write_facets(tmp_path, facets)

        for sid in ("alpha", "beta"):
            data = json.loads((tmp_path / "facets" / f"{sid}.json").read_text(encoding="utf-8"))
            assert data["session_id"] == sid


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    """LLM エラーがパイプライン全体を通じて正しく伝播する。"""

    def test_invalid_llm_json_raises_facets_generation_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LLM が不正 JSON を返したとき FacetsGenerationError がパイプラインから raise される。"""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        block = MagicMock()
        block.type = "text"
        block.text = "This is not JSON"
        mock_response = MagicMock()
        mock_response.content = [block]
        mock_messages = MagicMock()
        mock_messages.create.return_value = mock_response

        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages = mock_messages
            client = AnthropicClient()
        client._client.messages = mock_messages  # noqa: SLF001

        session = _make_session()
        with pytest.raises(FacetsGenerationError, match="not valid JSON"):
            client.generate_facets_from_session(session, _BASE_META)

    def test_missing_api_key_raises_before_pipeline(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """API キーがない場合、パイプライン開始前に OSError が raise される。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(OSError, match="ANTHROPIC_API_KEY"):
            AnthropicClient()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _assert_facets_schema(data: dict, expected_session_id: str) -> None:
    """Facets JSON の全フィールドが存在し、型が正しいことを検証する。"""
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
    assert required_keys.issubset(data.keys()), f"Missing keys: {required_keys - set(data.keys())}"
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["session_id"] == expected_session_id
    for str_field in ("project_area", "primary_goal", "session_type", "inferred_satisfaction"):
        assert isinstance(data[str_field], str), f"{str_field} should be str"
    for list_field in ("wins", "frictions", "suggested_rules", "suggested_patterns"):
        assert isinstance(data[list_field], list), f"{list_field} should be list"
