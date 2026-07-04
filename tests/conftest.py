"""共享 pytest fixture — 覆盖 DB、Redis、LLM、Agent、采集器等常用 mock。

设计原则：
- 默认 mock，显式 opt-in 才能访问真实外部资源。
- unit 层不连真实 DB、不外网请求、不调真实 LLM。
- 真实采集 / DB / 模型调用统一放到 integration / live smoke 层。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ── 环境与目录 ──────────────────────────────────────────────────


@pytest.fixture(scope="session")
def project_root() -> Path:
    """项目根目录。"""
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """隔离临时工作目录（输出 / 报告 / trace）。"""
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "outputs").mkdir(exist_ok=True)
    (ws / "raw").mkdir(exist_ok=True)
    (ws / "parsed").mkdir(exist_ok=True)
    return ws


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """统一设置测试环境变量，禁止误连真实外部服务。"""
    overrides: dict[str, str] = {
        "APP_ENV": "test",
        "DATABASE_URL": "sqlite:///:memory:",
        "REDIS_URL": "redis://localhost:6379/15",
        "LLM_PROVIDER": "mock",
        "OPENAI_API_KEY": "sk-test-placeholder",
        "OPENAI_BASE_URL": "http://127.0.0.1:9999/v1",
        "STORAGE_ROOT": "/tmp/finance-agent-test-storage",
    }
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    return overrides


# ── 数据层 mock ─────────────────────────────────────────────────


@pytest.fixture
def mock_db_session() -> MagicMock:
    """mock SQLAlchemy Session — add / commit / rollback / close。"""
    session = MagicMock(name="mock_db_session")
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    session.execute = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()
    # query chain mock
    query_mock = MagicMock(name="mock_query")
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.first.return_value = None
    query_mock.all.return_value = []
    query_mock.count.return_value = 0
    session.query.return_value = query_mock
    return session


@pytest.fixture
def mock_redis() -> MagicMock:
    """mock Redis client — get / set / exists / delete。"""
    client = MagicMock(name="mock_redis")
    client.get.return_value = None
    client.set.return_value = True
    client.exists.return_value = 0
    client.delete.return_value = 1
    client.keys.return_value = []
    client.scan_iter.return_value = []
    return client


# ── LLM mock ────────────────────────────────────────────────────


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """mock LLMGateway / OpenAI client，返回 LLMResponse 兼容结构。"""
    client = MagicMock(name="mock_llm_client")
    client.chat_sync.return_value = _make_mock_llm_response("mock analysis result")
    client.chat.return_value = _make_mock_llm_response("mock analysis result")
    # 兼容 OpenAI client 的 chat.completions.create
    completion_mock = MagicMock(name="mock_completion")
    choice_mock = MagicMock(name="mock_choice")
    choice_mock.message.content = "mock analysis result"
    completion_mock.choices = [choice_mock]
    completion_mock.model = "mock-model"
    usage_mock = MagicMock(name="mock_usage")
    usage_mock.prompt_tokens = 10
    usage_mock.completion_tokens = 20
    usage_mock.total_tokens = 30
    completion_mock.usage = usage_mock
    chat_mock = MagicMock(name="mock_chat")
    completions_mock = MagicMock(name="mock_completions")
    completions_mock.create.return_value = completion_mock
    chat_mock.completions = completions_mock
    client.chat = chat_mock
    return client


def _make_mock_llm_response(content: str) -> MagicMock:
    """构建与 apps.llm.gateway.LLMResponse 兼容的 mock 对象。"""
    r = MagicMock(name="LLMResponse")
    r.content = content
    r.model = "mock-model"
    r.provider = "mock"
    r.usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    r.latency_ms = 50
    r.cached = False
    r.prompt_tokens = 10
    r.completion_tokens = 20
    r.total_tokens = 30
    return r


# ── 数据样例 — 贴合项目真实 schema ──────────────────────────────


@pytest.fixture
def sample_trace_payload() -> dict[str, Any]:
    """报告溯源样例（用于 report / trace 相关测试）。"""
    return {
        "trace_id": "trace-test-001",
        "report_id": "gold_daily_20260615",
        "task_type": "gold_daily_analysis",
        "created_at": "2026-06-15T12:00:00Z",
        "analysis_date": "2026-06-15",
        "sources": [
            {
                "source_id": "fred_dgs10_20260615",
                "source_type": "official_data",
                "name": "FRED DGS10",
                "url": "https://fred.stlouisfed.org/series/DGS10",
                "data_date": "2026-06-15",
                "retrieved_at": "2026-06-15T12:00:00Z",
                "used_for": ["10Y nominal yield"],
            },
        ],
        "uploaded_files": [],
        "screenshots": [],
        "model_steps": [
            {"step": "macro_regime", "input_sources": ["fred_dgs10_20260615"], "output": "real_yield_pressure"},
        ],
        "assumptions": [],
        "warnings": [],
    }


@pytest.fixture
def sample_market_snapshot() -> dict[str, Any]:
    """宏观指标快照样例（贴合 analysis snapshot 真实字段）。"""
    return {
        "as_of": "2026-06-15",
        "indicators": {
            "DGS10": {"value": 4.30, "change_1w": -0.05},
            "DGS2": {"value": 4.05, "change_1w": 0.02},
            "T10YIE": {"value": 2.35, "change_1w": 0.02},
            "REAL_YIELD_10Y": {"value": 1.95, "change_1w": -0.07},
            "DXY": {"value": 97.8, "change_1w": -0.8},
            "USDJPY": {"value": 144.2, "change_1w": 1.2},
            "CL1": {"value": 68.5, "change_1w": -0.3},
            "RRPONTSYD": {"value": 82.0, "change_1w": -12.0},
            "TGA": {"value": 510.0, "change_1w": -45.0},
            "WRESCRT": {"value": 3210.0, "change_1w": 18.0},
            "SOFR": {"value": 4.32, "change_1w": 0.0},
            "EFFR": {"value": 4.33, "change_1w": 0.0},
            "IORB": {"value": 4.40, "change_1w": 0.0},
            "HYG_OAS": {"value": 3.15, "change_1w": 0.05},
        },
    }


@pytest.fixture
def sample_cme_options_rows() -> list[dict[str, Any]]:
    """CME 期权明细样例（贴合 CME Parser 真实字段）。"""
    return [
        {
            "expiry": "JUL26",
            "strike": 4600,
            "option_type": "CALL",
            "settlement": 0.0,
            "delta": 0.55,
            "implied_volatility": 0.16,
            "open_interest": 4520,
            "oi_change": 280,
            "total_volume": 1250,
            "block_volume": 800,
            "pnt_volume": 60,
            "futures_price": 4498.5,
        },
        {
            "expiry": "JUL26",
            "strike": 4500,
            "option_type": "CALL",
            "settlement": 0.0,
            "delta": 0.48,
            "implied_volatility": 0.155,
            "open_interest": 5100,
            "oi_change": -150,
            "total_volume": 980,
            "block_volume": 350,
            "pnt_volume": 40,
            "futures_price": 4498.5,
        },
        {
            "expiry": "JUL26",
            "strike": 4400,
            "option_type": "PUT",
            "settlement": 0.0,
            "delta": -0.42,
            "implied_volatility": 0.17,
            "open_interest": 3800,
            "oi_change": 120,
            "total_volume": 1100,
            "block_volume": 500,
            "pnt_volume": 25,
            "futures_price": 4498.5,
        },
        {
            "expiry": "JUL26",
            "strike": 4300,
            "option_type": "PUT",
            "settlement": 0.0,
            "delta": -0.28,
            "implied_volatility": 0.175,
            "open_interest": 6200,
            "oi_change": 600,
            "total_volume": 2100,
            "block_volume": 1500,
            "pnt_volume": 80,
            "futures_price": 4498.5,
        },
    ]


@pytest.fixture
def sample_report_context(
    sample_trace_payload: dict[str, Any],
    sample_market_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """报告生成上下文样例。"""
    return {
        "trace": sample_trace_payload,
        "market_snapshot": sample_market_snapshot,
        "raw_text": "本报告基于 FRED / CME / Jin10 数据生成。",
        "analysis_type": "gold_daily",
        "report_date": "2026-06-15",
    }


@pytest.fixture
def sample_agent_input_snapshot() -> dict[str, Any]:
    """Agent 入参 snapshot 样例（直接兼容现有 Agent 测试）。"""
    return {
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "macro": "macro:2026-05-14",
            "options": "cme-options:2026-05-14",
        },
        "metadata": {
            "symbol": "XAUUSD",
            "as_of": "2026-05-14",
            "unavailable_modules": [],
        },
        "macro": {
            "status": "available",
            "data": {
                "as_of": "2026-05-14",
                "indicators": {
                    "DGS10": {"value": 4.30, "change_1w": -0.05},
                    "T10YIE": {"value": 2.35, "change_1w": 0.02},
                    "REAL_YIELD_10Y": {"value": 1.95, "change_1w": -0.07},
                    "DXY": {"value": 97.8, "change_1w": -0.8},
                    "RRPONTSYD": {"value": 82.0},
                    "TGA": {"value": 510.0, "change_1w": -45.0},
                    "WRESBAL": {"value": 3210.0, "change_1w": 18.0},
                    "SOFR": {"value": 4.32},
                    "EFFR": {"value": 4.33},
                    "IORB": {"value": 4.40},
                },
            },
        },
        "source_refs": [
            {"symbol": "DGS10", "source": "fred"},
            {"symbol": "DXY", "source": "tradingview"},
        ],
    }


@pytest.fixture
def fixed_utc_now() -> datetime:
    """固定 UTC 时间，避免测试因时间漂移 flaky。"""
    return datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


# ── pytest 配置钩子 ─────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """注册自定义 markers。"""
    config.addinivalue_line("markers", "unit: fast isolated tests with mocks (default)")
    config.addinivalue_line("markers", "integration: tests requiring local services (DB, Redis)")
    config.addinivalue_line("markers", "live: tests requiring external network or real credentials")
    config.addinivalue_line("markers", "slow: tests that are slow even with mocks")
