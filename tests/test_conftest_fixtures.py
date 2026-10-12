"""验证 conftest.py 共享 fixture 加载正确，样例数据 schema 合法。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


# ── 环境 fixture 验证 ────────────────────────────────────────────


class TestEnvFixtures:
    def test_project_root_is_finance_agent(self, project_root: Path) -> None:
        assert (project_root / "pyproject.toml").exists()
        assert (project_root / "AGENTS.md").exists()
        assert (project_root / "apps").is_dir()

    def test_tmp_workspace_has_expected_dirs(self, tmp_workspace: Path) -> None:
        assert (tmp_workspace / "outputs").exists()
        assert (tmp_workspace / "raw").exists()
        assert (tmp_workspace / "parsed").exists()

    def test_mock_env_sets_test_variables(self, mock_env: dict[str, str]) -> None:
        import os

        assert os.environ["APP_ENV"] == "test"
        assert os.environ["DATABASE_URL"] == "sqlite:///:memory:"
        assert os.environ["LLM_PROVIDER"] == "mock"


# ── 数据层 mock 验证 ─────────────────────────────────────────────


class TestDataMocks:
    def test_mock_db_session_add_commit_rollback_close(self, mock_db_session: MagicMock) -> None:
        mock_db_session.add("fake_object")
        mock_db_session.commit()
        mock_db_session.rollback()
        mock_db_session.close()
        mock_db_session.add.assert_called_once_with("fake_object")
        mock_db_session.commit.assert_called_once()
        mock_db_session.rollback.assert_called_once()
        mock_db_session.close.assert_called_once()

    def test_mock_db_session_query_chain(self, mock_db_session: MagicMock) -> None:
        mock_db_session.execute.return_value.fetchall.return_value = [{"id": 1}]
        result = mock_db_session.execute("SELECT 1")
        assert result.fetchall() == [{"id": 1}]

    def test_mock_redis_defaults(self, mock_redis: MagicMock) -> None:
        assert mock_redis.get("any_key") is None
        assert mock_redis.exists("any_key") == 0
        assert mock_redis.delete("any_key") == 1
        assert mock_redis.set("key", "value") is True


# ── LLM mock 验证 ────────────────────────────────────────────────


class TestLLMFixtures:
    def test_mock_llm_client_chat_sync_returns_compatible_response(self, mock_llm_client: MagicMock) -> None:
        response = mock_llm_client.chat_sync([{"role": "user", "content": "test"}])
        assert response.content == "mock analysis result"
        assert response.model == "mock-model"
        assert response.provider == "mock"

    def test_mock_llm_client_openai_compat(self, mock_llm_client: MagicMock) -> None:
        completion = mock_llm_client.chat.completions.create(
            model="mock-model",
            messages=[{"role": "user", "content": "test"}],
        )
        assert completion.choices[0].message.content == "mock analysis result"
        assert completion.model == "mock-model"


# ── 样例数据 schema 验证 ─────────────────────────────────────────


class TestSamplePayloads:
    def test_sample_trace_payload_has_required_fields(self, sample_trace_payload: dict[str, Any]) -> None:
        assert "trace_id" in sample_trace_payload
        assert "report_id" in sample_trace_payload
        assert "sources" in sample_trace_payload
        assert isinstance(sample_trace_payload["sources"], list)

    def test_sample_market_snapshot_has_core_indicators(self, sample_market_snapshot: dict[str, Any]) -> None:
        indicators = sample_market_snapshot["indicators"]
        for key in ("DGS10", "DXY", "SOFR", "TGA", "REAL_YIELD_10Y"):
            assert key in indicators, f"Missing indicator: {key}"

    def test_sample_cme_options_rows_has_required_fields(self, sample_cme_options_rows: list[dict[str, Any]]) -> None:
        assert len(sample_cme_options_rows) == 4
        for row in sample_cme_options_rows:
            for field in ("expiry", "strike", "option_type", "open_interest", "delta"):
                assert field in row, f"Missing field {field} in {row}"

    def test_sample_agent_input_snapshot_matches_existing_tests(
        self, sample_agent_input_snapshot: dict[str, Any]
    ) -> None:
        """验证该 fixture 可替代现有测试中手写的 _snapshot() / _available_snapshot()。"""
        assert "snapshot_id" in sample_agent_input_snapshot
        assert "macro" in sample_agent_input_snapshot
        assert sample_agent_input_snapshot["macro"]["status"] == "available"
        assert sample_agent_input_snapshot["macro"]["data"]["indicators"]["DGS10"]["value"] == 4.30


class TestTimeFixtures:
    def test_fixed_utc_now_is_stable(self, fixed_utc_now: Any) -> None:
        assert str(fixed_utc_now) == "2026-06-15 12:00:00+00:00"


# ── pytest marker 验证 ───────────────────────────────────────────


@pytest.mark.slow
def test_slow_marker_registered() -> None:
    """仅验证 slow marker 可被 pytest 识别。"""
    assert True
