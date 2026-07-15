"""Data Ingestion immediate source test / preview contract tests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api import main
from apps.api.schemas.data_source import DataSourceTestRequest
from database.models.execution import ExecutionEvent, RunArtifact, ensure_execution_tables
from database.models.task import ensure_task_tables


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


class _FakeMCPClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def list_flash(self):
        return {
            "status": 200,
            "data": {
                "items": [
                    {"id": "flash-1", "time": "2026-06-13 09:30:00", "content": "黄金突破关键位"},
                    {"id": "flash-2", "time": "2026-06-13 09:31:00", "content": "美联储官员讲话"},
                    {"id": "flash-3", "time": "2026-06-13 09:32:00", "content": "原油库存更新"},
                ]
            },
        }


class _FakeMarketMCPClient(_FakeMCPClient):
    quote_payload = {"status": 200, "data": {"code": "XAUUSD", "price": "4072.10"}}
    kline_payload = {
        "status": 200,
        "data": {
            "klines": [
                {"time": 1784044200, "close": "4071.24"},
                {"time": 1784044140, "close": "4071.58"},
            ]
        },
    }

    def get_quote(self, code):
        return self.quote_payload

    def get_kline(self, code, count):
        return self.kline_payload


def _write_web_flash_briefs_artifact(
    project_root: Path,
    *,
    include_important: bool = True,
    include_vip: bool = True,
) -> Path:
    artifact_path = (
        project_root
        / "storage"
        / "features"
        / "news"
        / "2026-06-23"
        / "run-web"
        / "jin10_web_flash_briefs.json"
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "retrieved_date": "2026-06-23",
                "jin10_web_flash_briefs": {
                    "status": "ok",
                    "brief_count": int(include_important) + int(include_vip),
                    "briefs": [
                        *(
                            [
                                {
                                    "source_key": "jin10_web_important_flash",
                                    "headline": "重要快讯：黄金突破关键阻力",
                                    "display_bucket": "important",
                                    "published_at": "2026-06-23 09:30:00",
                                    "url": "https://www.jin10.com/flash/important-1",
                                    "access_status": "public",
                                    "verification_status": "verified",
                                }
                            ]
                            if include_important
                            else []
                        ),
                        *(
                            [
                                {
                                    "source_key": "jin10_web_vip_flash",
                                    "headline": "VIP快讯：机构持仓更新",
                                    "display_bucket": "vip",
                                    "published_at": "2026-06-23 09:31:00",
                                    "url": "https://www.jin10.com/flash/vip-1",
                                    "access_status": "vip_required",
                                    "verification_status": "profile_required",
                                }
                            ]
                            if include_vip
                            else []
                        ),
                    ],
                    "data_quality": {"source": "fixture"},
                    "source_refs": [{"source_key": "jin10_web_flash", "status": "ok"}],
                    "artifact_refs": [
                        {"file_path": "storage/features/news/2026-06-23/run-web/jin10_web_flash_briefs.json"}
                    ],
                    "quality_flags": {},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return artifact_path


def test_ingestion_source_test_runs_jin10_flash_probe_and_archives_preview(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service.Jin10MCPClient", _FakeMCPClient)

    response = main.api_ingestion_source_test(
        "jin10_mcp_flash",
        body=DataSourceTestRequest(actor="codex", reason="manual preview", request_id="probe-001", limit=2),
        db=session,
    )

    assert response.status == "ok"
    assert response.source_key == "jin10_mcp_flash"
    assert response.run_id is not None
    assert response.duration_ms >= 0
    assert response.summary["item_count"] == 3
    assert response.summary["sample_count"] == 2
    assert response.preview == [
        {"id": "flash-1", "published_at": "2026-06-13 09:30:00", "content_excerpt": "黄金突破关键位"},
        {"id": "flash-2", "published_at": "2026-06-13 09:31:00", "content_excerpt": "美联储官员讲话"},
    ]
    assert response.artifacts["raw_path"].startswith("storage/probes/ingestion/")
    assert response.artifacts["parsed_path"].startswith("storage/probes/ingestion/")
    assert (tmp_path / response.artifacts["raw_path"]).exists()
    parsed_payload = json.loads((tmp_path / response.artifacts["parsed_path"]).read_text(encoding="utf-8"))
    assert parsed_payload["source_key"] == "jin10_mcp_flash"
    assert parsed_payload["status"] == "ok"

    run = main.api_run_detail(response.run_id, db=session).model_dump(mode="json")
    assert run["task_type"] == "ingestion_source_test"
    assert run["status"] == "success"
    assert run["steps"][0]["task_kind"] == "source_probe"
    assert run["steps"][0]["source_refs"][0]["source_id"] == "jin10_mcp_flash"
    assert run["steps"][0]["artifact_refs"][0]["file_path"] == response.artifacts["raw_path"]

    events = (
        session.query(ExecutionEvent)
        .filter(ExecutionEvent.run_id == uuid.UUID(response.run_id))
        .order_by(ExecutionEvent.created_at.asc(), ExecutionEvent.event_type.asc())
        .all()
    )
    event_types = [event.event_type for event in events]
    assert "RUN_STARTED" in event_types
    assert "RUN_FINISHED" in event_types
    assert "TASK_STARTED" in event_types
    assert "TASK_FINISHED" in event_types
    artifacts = session.query(RunArtifact).filter(RunArtifact.run_id == uuid.UUID(response.run_id)).all()
    assert {artifact.file_path for artifact in artifacts} >= {
        response.artifacts["raw_path"],
        response.artifacts["parsed_path"],
    }


def test_ingestion_source_test_runs_gold_and_silver_etf_probe(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()

    def fake_fetch(*, client, retrieved_date, asset, config, fetched_at=None):
        del client, fetched_at
        return {
            "source_key": "jin10_minipro_etf_reports",
            "asset": asset,
            "attr_id": config["attr_id"],
            "fund_name": config["fund_name"],
            "fetched_at": f"{retrieved_date}T00:00:00+00:00",
            "request_params": {"attr_id": config["attr_id"]},
            "payload": {
                "status": 200,
                "data": [
                    {
                        "trust": 1003.59 if asset == "gold" else 15052.89,
                        "change": 4.566 if asset == "gold" else -8.43,
                        "value": 110_000_000_000 if asset == "gold" else 27_486_155_500,
                        "reported_on": "2026-07-20",
                    }
                ],
            },
        }

    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "apps.api.services.ingestion_source_test_service.fetch_jin10_etf_report",
        fake_fetch,
    )

    response = main.api_ingestion_source_test(
        "jin10_minipro_etf_reports",
        body=DataSourceTestRequest(limit=2),
        db=session,
    )

    assert response.status == "ok"
    assert response.data_status.value == "live"
    assert response.summary["report_count"] == 2
    assert [item["asset"] for item in response.preview] == ["gold", "silver"]
    assert response.preview[1]["holdings_tonnes"] == 15052.89
    assert response.preview[1]["change_tonnes"] == -8.43
    assert (tmp_path / response.artifacts["raw_path"]).exists()
    assert (tmp_path / response.artifacts["parsed_path"]).exists()


def test_ingestion_source_test_market_probe_is_live_when_quote_and_kline_exist(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service.Jin10MCPClient", _FakeMarketMCPClient)

    response = main.api_ingestion_source_test("jin10_mcp_market", body=DataSourceTestRequest(limit=2), db=session)

    assert response.status == "ok"
    assert response.data_status.value == "live"
    assert response.summary["quote_available"] is True
    assert response.summary["kline_available"] is True
    assert response.summary["missing_components"] == []


def test_ingestion_source_test_market_probe_is_partial_when_quote_is_missing(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()

    class PartialMarketClient(_FakeMarketMCPClient):
        quote_payload = {}

    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service.Jin10MCPClient", PartialMarketClient)

    response = main.api_ingestion_source_test("jin10_mcp_market", body=DataSourceTestRequest(limit=2), db=session)

    assert response.status == "partial"
    assert response.data_status.value == "partial"
    assert response.summary["reason_code"] == "market_probe_partial"
    assert response.summary["missing_components"] == ["quote"]
    assert response.preview[0]["price"] is None
    run = main.api_run_detail(response.run_id, db=session).model_dump(mode="json")
    assert run["status"] == "partial_success"


def test_ingestion_source_test_market_probe_is_unavailable_when_all_components_are_missing(
    monkeypatch, tmp_path: Path
) -> None:
    session = _make_session()

    class EmptyMarketClient(_FakeMarketMCPClient):
        quote_payload = {}
        kline_payload = {}

    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service.Jin10MCPClient", EmptyMarketClient)

    response = main.api_ingestion_source_test("jin10_mcp_market", body=DataSourceTestRequest(limit=2), db=session)

    assert response.status == "unavailable"
    assert response.data_status.value == "unavailable"
    assert response.summary["reason_code"] == "market_probe_unavailable"
    assert response.summary["missing_components"] == ["quote", "kline"]
    run = main.api_run_detail(response.run_id, db=session).model_dump(mode="json")
    assert run["status"] == "failed"


def test_ingestion_source_test_reads_web_important_flash_latest_artifact(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    _write_web_flash_briefs_artifact(tmp_path)

    response = main.api_ingestion_source_test(
        "jin10_web_important_flash",
        body=DataSourceTestRequest(actor="codex", reason="web important preview", request_id="probe-web-important", limit=5),
        db=session,
    )

    assert response.status == "ok"
    assert response.data_status == "live"
    assert response.summary["source_key"] == "jin10_web_important_flash"
    assert response.summary["matching_count"] == 1
    assert response.summary["sample_count"] == 1
    assert response.preview == [
        {
            "headline": "重要快讯：黄金突破关键阻力",
            "display_bucket": "important",
            "published_at": "2026-06-23 09:30:00",
            "url": "https://www.jin10.com/flash/important-1",
            "access_status": "public",
            "verification_status": "verified",
        }
    ]
    assert (tmp_path / response.artifacts["raw_path"]).exists()
    assert (tmp_path / response.artifacts["parsed_path"]).exists()
    raw_payload = json.loads((tmp_path / response.artifacts["raw_path"]).read_text(encoding="utf-8"))
    raw_text = json.dumps(raw_payload, ensure_ascii=False)
    assert "VIP快讯：机构持仓更新" not in raw_text
    assert "jin10_web_vip_flash" not in raw_text


def test_ingestion_source_test_reads_web_vip_flash_latest_artifact(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    _write_web_flash_briefs_artifact(tmp_path)

    response = main.api_ingestion_source_test(
        "jin10_web_vip_flash",
        body=DataSourceTestRequest(actor="codex", reason="web vip preview", request_id="probe-web-vip", limit=5),
        db=session,
    )

    assert response.status == "ok"
    assert response.data_status == "live"
    assert response.summary["source_key"] == "jin10_web_vip_flash"
    assert response.summary["matching_count"] == 1
    assert response.summary["sample_count"] == 1
    assert response.preview == [
        {
            "headline": "VIP快讯：机构持仓更新",
            "display_bucket": "vip",
            "published_at": "2026-06-23 09:31:00",
            "url": "https://www.jin10.com/flash/vip-1",
            "access_status": "vip_required",
            "verification_status": "profile_required",
        }
    ]
    assert response.preview[0]["access_status"] == "vip_required"
    assert (tmp_path / response.artifacts["raw_path"]).exists()
    assert (tmp_path / response.artifacts["parsed_path"]).exists()
    raw_payload = json.loads((tmp_path / response.artifacts["raw_path"]).read_text(encoding="utf-8"))
    raw_text = json.dumps(raw_payload, ensure_ascii=False)
    assert "重要快讯：黄金突破关键阻力" not in raw_text
    assert "jin10_web_important_flash" not in raw_text


def test_ingestion_source_test_web_flash_zero_match_returns_partial(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    _write_web_flash_briefs_artifact(tmp_path, include_important=False, include_vip=True)

    response = main.api_ingestion_source_test(
        "jin10_web_important_flash",
        body=DataSourceTestRequest(actor="codex", reason="web important no match", request_id="probe-web-zero"),
        db=session,
    )

    assert response.status == "no_matching_briefs"
    assert response.data_status == "partial"
    assert response.preview == []
    assert response.summary["reason_code"] == "no_matching_briefs"
    assert response.summary["matching_count"] == 0


def test_ingestion_source_test_web_flash_without_artifact_returns_partial(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)

    response = main.api_ingestion_source_test(
        "jin10_web_important_flash",
        body=DataSourceTestRequest(actor="codex", reason="missing web flash artifact", request_id="probe-web-missing"),
        db=session,
    )

    assert response.status == "no_latest_artifact"
    assert response.data_status == "partial"
    assert response.preview == []
    assert response.summary["reason_code"] == "no_latest_artifact"
    assert response.summary["source_key"] == "jin10_web_important_flash"
    assert response.summary["method"] == "latest.jin10_web_flash_briefs"


def test_ingestion_source_test_web_flash_malformed_artifact_returns_partial(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    artifact_path = tmp_path / "storage/features/news/2026-06-23/run-bad/jin10_web_flash_briefs.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps({"brief_count": "bad"}), encoding="utf-8")

    response = main.api_ingestion_source_test(
        "jin10_web_important_flash",
        body=DataSourceTestRequest(actor="codex", reason="malformed web flash artifact", request_id="probe-web-bad"),
        db=session,
    )

    assert response.status == "malformed_latest_artifact"
    assert response.data_status == "partial"
    assert response.preview == []
    assert response.summary["reason_code"] == "malformed_latest_artifact"
    assert response.summary["artifact_path"] == artifact_path.relative_to(tmp_path).as_posix()


@dataclass
class _DatacenterFetchResult:
    status: str = "schema_changed"
    slug: str = "dc_etf_gold"
    raw_html_path: str = "storage/probes/ingestion/2026-06-13/jin10_datacenter_reports/run/shell.html"
    raw_js_path: str = "storage/probes/ingestion/2026-06-13/jin10_datacenter_reports/run/latest.js"
    error_message: str = "dataCenter_data assignment not found"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "slug": self.slug,
            "raw_html_path": self.raw_html_path,
            "raw_js_path": self.raw_js_path,
            "error_message": self.error_message,
            "source_refs": [{"source_key": "jin10_datacenter_reports", "status": self.status}],
        }


def test_ingestion_source_test_returns_datacenter_schema_changed(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "apps.api.services.ingestion_source_test_service.fetch_datacenter_report",
        lambda **kwargs: _DatacenterFetchResult(),
    )

    response = main.api_ingestion_source_test(
        "jin10_datacenter_reports",
        body=DataSourceTestRequest(actor="codex", reason="datacenter probe", request_id="probe-dc", limit=3),
        db=session,
    )

    assert response.status == "schema_changed"
    assert response.data_status == "partial"
    assert response.summary["slug"] == "dc_etf_gold"
    assert response.summary["reason_code"] == "schema_changed"
    assert response.preview == []


def test_ingestion_source_test_runs_datacenter_with_specific_slug(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)

    captured_slugs: list[str] = []

    def _fake_fetch(*, slug: str, **kwargs):
        captured_slugs.append(slug)
        result = _DatacenterFetchResult(slug=slug, status="ok")
        return result

    monkeypatch.setattr(
        "apps.api.services.ingestion_source_test_service.fetch_datacenter_report",
        _fake_fetch,
    )

    response = main.api_ingestion_source_test(
        "jin10_datacenter_reports",
        body=DataSourceTestRequest(actor="codex", reason="nonfarm probe", request_id="probe-nfp", slug="dc_nonfarm_payrolls"),
        db=session,
    )

    assert response.status == "ok"
    assert captured_slugs == ["dc_nonfarm_payrolls"]
    assert response.summary["slug"] == "dc_nonfarm_payrolls"


def test_ingestion_source_test_rejects_unsupported_datacenter_slug(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)

    response = main.api_ingestion_source_test(
        "jin10_datacenter_reports",
        body=DataSourceTestRequest(actor="codex", reason="bad slug", request_id="probe-bad", slug="dc_unknown_slug"),
        db=session,
    )

    assert response.status == "unsupported_slug"
    assert response.data_status == "unavailable"
    assert "not in the allowed datacenter slug registry" in response.summary["reason"]


def test_ingestion_source_test_does_not_auto_fetch_svip_reports(monkeypatch, tmp_path: Path) -> None:
    session = _make_session()
    monkeypatch.setattr("apps.api.services.ingestion_source_test_service._PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "apps.api.services.ingestion_source_test_service.DEFAULT_JIN10_BROWSER_PROFILE",
        tmp_path / "missing-profile",
    )

    response = main.api_ingestion_source_test(
        "jin10_svip_reports",
        body=DataSourceTestRequest(actor="codex", reason="svip probe", request_id="probe-svip"),
        db=session,
    )

    assert response.status == "login_required"
    assert response.data_status == "manual_required"
    assert response.summary["auto_fetch"] is False
    assert "browser_profile" in response.summary["reason"]
    assert response.preview == []
