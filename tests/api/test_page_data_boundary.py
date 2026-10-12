from __future__ import annotations

import asyncio
import json
from pathlib import Path

from apps.api.services.page_data_boundary import PageDataBoundaryMiddleware


def _response(payload, *, path: str = "/api/example", method: str = "GET") -> tuple[int, dict]:
    async def endpoint(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": json.dumps(payload).encode("utf-8"),
                "more_body": False,
            }
        )

    messages = []

    request_received = False

    async def receive():
        nonlocal request_received
        if request_received:
            return {"type": "http.disconnect"}
        request_received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "client": ("test", 50000),
        "server": ("test", 80),
    }
    asyncio.run(PageDataBoundaryMiddleware(endpoint)(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], json.loads(body)


def _binary_response(*, path: str, media_type: str, body: bytes) -> tuple[int, bytes, str]:
    async def endpoint(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", media_type.encode("ascii"))],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})

    messages = []

    request_received = False

    async def receive():
        nonlocal request_received
        if request_received:
            return {"type": "http.disconnect"}
        request_received = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "client": ("test", 50000),
        "server": ("test", 80),
    }
    asyncio.run(PageDataBoundaryMiddleware(endpoint)(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    content_type = next(
        value.decode("latin-1")
        for key, value in start.get("headers") or []
        if key.lower() == b"content-type"
    )
    return start["status"], response_body, content_type


def test_execution_page_filters_raw_parsed_ods_and_step_json_but_keeps_feature_business_fields() -> None:
    payload = {
        "run_id": "run-1",
        "status": "success",
        "input_json": {"raw_body": "must-not-leak"},
        "output_json": {"rows": [{"secret": "must-not-leak"}]},
        "source_refs": [
            {
                "source_id": "cme",
                "source_name": "CME",
                "source_type": "pdf",
                "url": "https://www.cmegroup.com/official",
                "file_path": "storage/raw/cme/bulletin.pdf",
            }
        ],
        "artifact_refs": [
            {"artifact_id": "raw", "artifact_type": "raw_file", "file_path": "storage/raw/cme/bulletin.pdf"},
            {"artifact_id": "parsed", "artifact_type": "parsed_file", "file_path": "storage/parsed/cme/detail.json"},
            {"artifact_id": "ods", "artifact_type": "structured_json", "file_path": "storage/ods/cme/rows.json"},
            {
                "artifact_id": "feature",
                "artifact_type": "feature_json",
                "file_path": "storage/features/cme/options.json",
            },
        ],
        "business": {"bias": "neutral", "confidence": 0.63},
        "scenario": {"path": "站稳 4130 后延续", "generated_from": {"model": "deterministic-rules"}},
    }
    status_code, body = _response(payload, path="/api/runs/run-1")

    assert status_code == 200
    assert body["status"] == "success"
    assert body["business"] == {"bias": "neutral", "confidence": 0.63}
    assert body["scenario"] == {
        "path": "站稳 4130 后延续",
        "generated_from": {"model": "deterministic-rules"},
    }
    assert "input_json" not in body and "output_json" not in body
    assert [item["artifact_id"] for item in body["artifact_refs"]] == ["feature"]
    assert body["source_refs"] == [
        {
            "source_id": "cme",
            "source_name": "CME",
            "source_type": "pdf",
            "url": "https://www.cmegroup.com/official",
        }
    ]


def test_direct_raw_artifact_lookup_is_forbidden_and_feature_lookup_remains_readable() -> None:
    raw = {
        "artifact": {
            "artifact_id": "raw-1",
            "artifact_type": "raw_file",
            "file_path": "storage/raw/news/item.json",
        },
        "metadata": {"source_name": "Jin10"},
    }
    status_code, body = _response(raw, path="/api/artifacts/raw-1")
    assert status_code == 403
    assert body["status"] == "forbidden"

    feature = {
        "artifact": {
            "artifact_id": "feature-1",
            "artifact_type": "feature_json",
            "file_path": "storage/features/news/brief.json",
        },
        "metadata": {"domain": "news", "brief_count": 2},
    }
    status_code, body = _response(feature, path="/api/artifacts/feature-1")
    assert status_code == 200
    assert body["artifact"]["artifact_id"] == "feature-1"
    assert "file_path" not in body["artifact"]
    assert body["metadata"] == {"domain": "news", "brief_count": 2}

    arbitrary = {
        "artifact": {
            "artifact_id": "arbitrary-1",
            "artifact_type": "analysis_md",
            "file_path": "/etc/passwd",
        }
    }
    status_code, _ = _response(arbitrary, path="/api/artifacts/arbitrary-1")
    assert status_code == 403

    original_json = {
        "artifact": {
            "artifact_id": "raw-json-1",
            "artifact_type": "structured_json",
            "file_path": "storage/outputs/jin10/run-1/raw_article_report.json",
        }
    }
    status_code, _ = _response(original_json, path="/api/artifacts/raw-json-1")
    assert status_code == 403


def test_source_trace_by_raw_artifact_is_forbidden() -> None:
    payload = {
        "artifact_refs": [
            {"artifact_id": "raw-1", "artifact_type": "raw_file", "file_path": "storage/raw/news/item.json"}
        ],
        "source_refs": [{"source_id": "jin10", "source_name": "Jin10", "source_type": "news"}],
    }
    status_code, _ = _response(payload, path="/api/source-trace/by-artifact/raw-1")
    assert status_code == 403


def test_report_content_and_feature_refs_remain_readable_without_internal_paths() -> None:
    payload = {
        "report_id": "report-1",
        "title": "Gold report",
        "content": "# Current judgment\nBullish only above the trigger.",
        "path": "storage/outputs/reports/report-1/analysis.md",
        "asset_base_url": "/api/reports/report-1/asset/analysis_md/",
        "source_refs": [
            {
                "source_id": "cme",
                "source_name": "CME",
                "source_type": "official",
                "captured_at": "2026-10-10T01:00:00+00:00",
                "url": "https://www.cmegroup.com/official",
                "endpoint": "/api/options/decision",
                "source_ref": "storage/raw/cme/source.pdf",
                "file_path": "storage/raw/cme/source.pdf",
            }
        ],
        "artifact_refs": [
            {
                "artifact_id": "analysis",
                "artifact_type": "analysis_md",
                "file_path": "storage/outputs/reports/report-1/analysis.md",
            },
            {
                "artifact_id": "feature",
                "artifact_type": "feature_json",
                "file_path": "storage/features/gold/snapshot.json",
            },
        ],
    }
    status_code, body = _response(payload, path="/api/reports/report-1/analysis")

    assert status_code == 200
    assert body["content"].startswith("# Current judgment")
    assert body["asset_base_url"].startswith("/api/reports/")
    assert "path" not in body
    assert {item["artifact_id"] for item in body["artifact_refs"]} == {"analysis", "feature"}
    assert all("file_path" not in item for item in body["artifact_refs"])
    assert body["source_refs"][0]["url"].startswith("https://")
    assert body["source_refs"][0]["endpoint"] == "/api/options/decision"
    assert "source_ref" not in body["source_refs"][0]
    assert "file_path" not in body["source_refs"][0]


def test_data_source_page_is_ads_status_summary_with_stale_and_missing_explicit() -> None:
    payload = {
        "sources": [
            {
                "source_key": "cme",
                "source_name": "CME",
                "source_group": "cme",
                "status": "stale",
                "error_message": "latest collection failed",
                "freshness_status": "stale",
                "latest_update_time": "2026-10-09T01:00:00+00:00",
                "artifact_evidence": {"collector_raw_artifact_path": "storage/raw/cme/a.pdf"},
                "metadata": {
                    "frontend_label": "CME options",
                    "source_url": "https://www.cmegroup.com/market-data.html?access_key=private",
                    "latest_raw_ref": {"raw_path": "storage/raw/cme/a.pdf"},
                    "artifact_layers": ["storage/raw/cme", "storage/features/cme"],
                },
            },
            {
                "source_key": "fedwatch",
                "source_name": "FedWatch",
                "source_group": "macro",
                "status": "unavailable",
                "error_message": "DWS snapshot missing",
                "freshness_status": "unknown",
                "metadata": {"frontend_label": "FedWatch"},
            },
        ]
    }
    status_code, body = _response(payload, path="/api/data-sources/status")

    assert status_code == 200
    stale, missing = body["sources"]
    assert stale["status"] == "stale"
    assert stale["error_message"] == "latest collection failed"
    assert stale["metadata"] == {"frontend_label": "CME options"}
    assert stale["source_url"] == "https://www.cmegroup.com/market-data.html"
    assert "artifact_evidence" not in stale
    assert missing["status"] == "unavailable"
    assert missing["error_message"] == "DWS snapshot missing"


def test_data_source_registry_omits_internal_storage_contract() -> None:
    payload = {
        "total": 1,
        "sources": [
            {
                "source_key": "cme",
                "source_name": "CME",
                "domain": "cme",
                "provider": "CME",
                "source_type": "official",
                "expected_frequency": "daily",
                "enabled": True,
                "metadata": {"artifact_layers": ["storage/raw/cme"]},
                "polling_strategy": {"query": "private collector query"},
            }
        ],
    }
    status_code, body = _response(payload, path="/api/data-sources/registry")

    assert status_code == 200
    assert body == {
        "total": 1,
        "sources": [
            {
                "source_key": "cme",
                "source_name": "CME",
                "domain": "cme",
                "provider": "CME",
                "source_type": "official",
                "expected_frequency": "daily",
                "enabled": True,
            }
        ],
    }


def test_processing_monitor_keeps_ads_status_and_removes_stage_paths() -> None:
    payload = {
        "status": "accepted",
        "generated_from": "storage/features/gold/run-1/overview.json",
        "source_health": {"status": "fresh", "as_of": "2026-10-10T01:00:00+00:00"},
        "trace_path": [
            {
                "node_id": "jin10_message_raw",
                "status": "covered",
                "artifact_refs": [
                    {
                        "artifact_id": "raw-1",
                        "artifact_type": "raw_file",
                        "file_path": "storage/raw/news/item.json",
                    },
                    {
                        "artifact_id": "feature-1",
                        "artifact_type": "feature_json",
                        "file_path": "storage/features/news/brief.json",
                    },
                ],
            }
        ],
    }

    status_code, body = _response(payload, path="/api/processing/overview")

    assert status_code == 200
    assert body["status"] == "accepted"
    assert body["source_health"]["status"] == "fresh"
    assert "generated_from" not in body
    assert body["trace_path"][0]["status"] == "covered"
    assert body["trace_path"][0]["artifact_refs"] == [
        {"artifact_id": "feature-1", "artifact_type": "feature_json"}
    ]


def test_ingestion_probe_post_returns_status_not_raw_preview_or_artifact_paths() -> None:
    payload = {
        "status": "ok",
        "action": "test",
        "source_key": "jin10_mcp_flash",
        "summary": {"item_count": 3, "artifact_path": "storage/raw/jin10/probe.json"},
        "preview": [{"content_excerpt": "unprocessed flash body"}],
        "artifacts": {
            "raw_path": "storage/raw/jin10/probe.json",
            "parsed_path": "storage/parsed/jin10/probe.json",
        },
        "artifact_refs": [
            {"artifact_id": "raw", "artifact_type": "raw_file", "file_path": "storage/raw/jin10/probe.json"}
        ],
    }
    status_code, body = _response(
        payload,
        path="/api/ingestion/sources/jin10_mcp_flash/test",
        method="POST",
    )

    assert status_code == 200
    assert body["status"] == "ok"
    assert body["summary"] == {"item_count": 3}
    assert body["preview"] == []
    assert body["artifacts"] == {}
    assert body["artifact_refs"] == []
    assert body["page_layer"] == "ADS"


def test_fedwatch_history_projects_factor_summary_not_ods_rows() -> None:
    payload = {
        "as_of": "2026-10-10T01:00:00+00:00",
        "items": [
            {
                "snapshot_id": "snap-1",
                "as_of": "2026-10-10T00:30:00+00:00",
                "collected_at": "2026-10-10T00:31:00+00:00",
                "parse_status": "ok",
                "raw_artifact_ref": "raw/fedwatch/snap-1.json",
                "rows": [{"meeting_date": "2026-12-16", "probability": 0.7}],
                "futures": [{"price": 95.0}],
                "factor": {
                    "health": {"status": "fresh", "quality_summary": {"total_probability": 1.0}},
                    "market_implied_path": {"next_meeting": {"date": "2026-12-16"}},
                    "repricing": {"direction": "easing"},
                    "source_refs": [{"source_name": "CME", "url": "https://www.cmegroup.com/fedwatch"}],
                },
            }
        ],
    }
    status_code, body = _response(payload, path="/api/market/fedwatch/history")

    assert status_code == 200
    item = body["items"][0]
    assert item["status"] == "fresh"
    assert item["repricing"]["direction"] == "easing"
    assert "rows" not in item and "futures" not in item and "raw_artifact_ref" not in item


def test_feishu_monitor_keeps_derived_brief_and_drops_unprocessed_message_body() -> None:
    payload = {
        "status": "available",
        "date": "2026-10-10",
        "message_count": 2,
        "messages": [
            {"message_id": "raw-only", "title": "raw headline", "summary": "raw body"},
            {
                "message_id": "derived",
                "title": "raw headline",
                "summary": "raw body",
                "published_at": "2026-10-10T01:00:00+00:00",
                "primary_url": "https://www.jin10.com/article/1",
                "article_brief": {"headline": "DWS headline", "analysis_summary": "DWS summary"},
                "trigger": {"priority": "high"},
                "blocked": False,
                "actionable": True,
            },
        ],
    }
    status_code, body = _response(payload, path="/api/news/feishu-jin10/messages")

    assert status_code == 200
    assert body["page_layer"] == "ADS"
    assert [item["message_id"] for item in body["messages"]] == ["derived"]
    assert body["messages"][0]["title"] == "DWS headline"
    assert body["messages"][0]["summary"] == "DWS summary"


def test_report_asset_resolver_allows_output_bundle_and_blocks_raw_or_parsed(tmp_path: Path, monkeypatch) -> None:
    from apps.api.services import report_service

    output_dir = tmp_path / "storage" / "outputs" / "reports" / "report-1"
    raw_dir = tmp_path / "storage" / "raw" / "reports" / "report-1"
    parsed_dir = tmp_path / "storage" / "parsed" / "reports" / "report-1"
    for directory in (output_dir, raw_dir, parsed_dir):
        directory.mkdir(parents=True)
        (directory / "analysis.md").write_text("report", encoding="utf-8")
        (directory / "chart.png").write_bytes(b"png")
        (directory / "source.pdf").write_bytes(b"pdf")

    monkeypatch.setattr(report_service._storage, "_PROJECT_ROOT", tmp_path)

    assert (
        report_service._resolve_report_asset_path("storage/outputs/reports/report-1/analysis.md", "chart.png")
        == output_dir / "chart.png"
    )
    assert report_service._resolve_report_asset_path("storage/raw/reports/report-1/analysis.md", "chart.png") is None
    assert report_service._resolve_report_asset_path("storage/parsed/reports/report-1/analysis.md", "chart.png") is None
    assert (
        report_service._resolve_report_asset_path("storage/outputs/reports/report-1/analysis.md", "source.pdf") is None
    )


def test_jin10_asset_resolver_does_not_fall_back_to_parsed_or_external_sources(tmp_path: Path, monkeypatch) -> None:
    from apps.api.services import report_service

    output = tmp_path / "storage/outputs/jin10/2026-10-10/run-1/figures/chart.png"
    parsed = tmp_path / "storage/parsed/jin10/2026-10-10/run-1/figures/chart.png"
    output.parent.mkdir(parents=True)
    parsed.parent.mkdir(parents=True)
    output.write_bytes(b"rendered")
    parsed.write_bytes(b"parsed")
    monkeypatch.setattr(report_service._storage, "_PROJECT_ROOT", tmp_path)

    assert report_service.get_jin10_report_bundle_asset_path("2026-10-10", "run-1", "figures/chart.png") == output

    output.unlink()
    assert report_service.get_jin10_report_bundle_asset_path("2026-10-10", "run-1", "figures/chart.png") is None


def test_jin10_report_bundle_excludes_raw_article_view_and_raw_only_bundle(tmp_path: Path, monkeypatch) -> None:
    from apps.api.services import report_service

    bundle = tmp_path / "storage/outputs/jin10/2026-10-10/run-1"
    bundle.mkdir(parents=True)
    (bundle / "raw_article_report.md").write_text("raw article body", encoding="utf-8")
    (bundle / "raw_article_report.json").write_text(
        json.dumps({"title": "raw title", "source_url": "https://www.jin10.com/raw"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(report_service._storage, "_PROJECT_ROOT", tmp_path)

    assert report_service.get_jin10_report_bundle("2026-10-10", "run-1") is None

    (bundle / "agent_analysis_report.md").write_text("derived analysis", encoding="utf-8")
    (bundle / "agent_analysis_report.json").write_text(
        json.dumps({"title": "derived title", "source_url": "https://www.jin10.com/article/1"}),
        encoding="utf-8",
    )
    result = report_service.get_jin10_report_bundle("2026-10-10", "run-1")

    assert set(result["views"]) == {"agent_analysis", "daily_visual"}
    assert result["views"]["agent_analysis"]["content"] == "derived analysis"
    assert "raw article body" not in json.dumps(result, ensure_ascii=False)


def test_report_page_artifact_policy_rejects_raw_article_source() -> None:
    from apps.api.schemas.common import ArtifactType
    from apps.api.schemas.report import ReportArtifact
    from apps.api.services.report_service import _page_report_artifact_allowed

    raw = ReportArtifact(
        artifact_id="raw-source",
        artifact_type=ArtifactType.source_md,
        file_path="storage/outputs/jin10/2026-10-10/run-1/raw_article_report.md",
    )
    derived = ReportArtifact(
        artifact_id="analysis",
        artifact_type=ArtifactType.analysis_md,
        file_path="storage/outputs/jin10/2026-10-10/run-1/agent_analysis_report.md",
    )

    assert _page_report_artifact_allowed(raw) is False
    assert _page_report_artifact_allowed(derived) is True


def test_jin10_page_report_reads_derived_output_and_never_raw_or_external(tmp_path: Path) -> None:
    from apps.api.services.page_jin10_report_service import get_page_jin10_report

    base = tmp_path / "storage/outputs/jin10/2026-10-10/run-1"
    base.mkdir(parents=True)
    (base / "daily_analysis.json").write_text(
        json.dumps({"family": "jin10_weekly_visual", "title": "Derived weekly"}),
        encoding="utf-8",
    )
    (base / "agent_analysis_report.md").write_text("derived business analysis", encoding="utf-8")
    (base / "raw_article_report.md").write_text("raw article must not leak", encoding="utf-8")
    external = tmp_path / "jin10-reports/2026-10-10/weekly/run-1"
    external.mkdir(parents=True)
    (external / "report.md").write_text("external raw must not leak", encoding="utf-8")

    result = get_page_jin10_report(
        report_type="weekly",
        date="2026-10-10",
        run_id="run-1",
        project_root=tmp_path,
    )

    assert result["status"] == "available"
    assert result["content"] == "derived business analysis"
    assert "raw article" not in json.dumps(result, ensure_ascii=False)
    assert "external raw" not in json.dumps(result, ensure_ascii=False)


def test_jin10_report_structured_payload_uses_derived_fields_not_raw_body(tmp_path: Path, monkeypatch) -> None:
    from apps.api.services import report_service

    run_dir = tmp_path / "storage/outputs/jin10/2026-10-10/run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "raw_article_report.json").write_text(
        json.dumps({"raw_body": "must not leak", "article_id": "1", "source_refs": []}),
        encoding="utf-8",
    )
    (run_dir / "agent_analysis_report.json").write_text(
        json.dumps({"analysis_summary": "derived conclusion", "scenario_paths": [{"name": "base"}]}),
        encoding="utf-8",
    )
    (run_dir / "daily_analysis.json").write_text(
        json.dumps({"family": "jin10_daily_visual", "trade_date": "2026-10-10"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(report_service._storage, "_PROJECT_ROOT", tmp_path)

    result = report_service._build_legacy_jin10_structured_payload(run_dir=run_dir, artifacts=[])

    assert result["analysis_summary"] == "derived conclusion"
    assert result["trade_date"] == "2026-10-10"
    assert "raw_body" not in result


def test_jin10_page_routes_use_dws_briefs_and_fail_closed_when_missing(monkeypatch) -> None:
    from apps.api.routes import jin10_market_routes

    monkeypatch.setattr(jin10_market_routes, "jin10_disabled", lambda: False)
    monkeypatch.setattr(jin10_market_routes, "get_jin10_web_flash_briefs_latest", lambda: None)
    missing = jin10_market_routes.api_jin10_flash()
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "dws_flash_unavailable"

    monkeypatch.setattr(
        jin10_market_routes,
        "get_jin10_web_flash_briefs_latest",
        lambda: {
            "status": "available",
            "brief_count": 1,
            "briefs": [{"headline": "derived", "analysis_summary": "business result"}],
            "as_of": "2026-10-10T01:00:00+00:00",
            "source_refs": [{"source_name": "Jin10", "url": "https://www.jin10.com"}],
        },
    )
    available = jin10_market_routes.api_jin10_flash()
    assert available["status"] == "available"
    assert available["items"][0]["analysis_summary"] == "business result"
    assert available["page_layer"] == "ADS"

    calendar = jin10_market_routes.api_jin10_calendar()
    assert calendar["status"] == "unavailable"
    assert calendar["reason"] == "dws_calendar_unavailable"


def test_options_page_route_disables_parsed_archive_fallback(monkeypatch) -> None:
    from apps.api.routes import options_routes

    captured = {}

    def decision(date, *, lookback_days, db, allow_archived_parse):
        captured.update(
            date=date,
            lookback_days=lookback_days,
            db=db,
            allow_archived_parse=allow_archived_parse,
        )
        return {"status": "unavailable", "reason": "dws_options_unavailable"}

    monkeypatch.setattr(options_routes, "get_options_decision", decision)
    result = options_routes.api_options_decision(date="2026-10-10", lookback_days=5, db=object())

    assert result["status"] == "unavailable"
    assert captured["allow_archived_parse"] is False


def test_page_news_read_model_uses_features_not_parsed_messages(tmp_path: Path) -> None:
    from apps.api.services.page_news_read_model_service import get_page_news_monitor

    parsed = tmp_path / "storage/parsed/news/jin10_feishu/2026-10-10/messages-1.json"
    parsed.parent.mkdir(parents=True)
    parsed.write_text(json.dumps({"messages": [{"content": "raw body must not be used"}]}), encoding="utf-8")
    feature = tmp_path / "storage/features/news/2026-10-10/run-1/jin10_article_briefs.json"
    feature.parent.mkdir(parents=True)
    feature.write_text(
        json.dumps(
            {
                "as_of": "2026-10-10T01:00:00+00:00",
                "briefs": [
                    {
                        "brief_id": "brief-1",
                        "source_url": "https://www.jin10.com/article/1",
                        "headline": "DWS headline",
                        "analysis_summary": "DWS summary",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = get_page_news_monitor(date="2026-10-10", project_root=tmp_path)

    assert result["status"] == "available"
    assert result["page_layer"] == "ADS"
    assert result["messages"][0]["title"] == "DWS headline"
    assert "raw body must not be used" not in json.dumps(result, ensure_ascii=False)


def test_fedwatch_page_view_returns_unavailable_without_factor() -> None:
    from apps.api.services.fedwatch_read_model_service import get_latest_fedwatch_factor_view

    class EmptyScalars:
        def first(self):
            return None

    class EmptySession:
        def scalars(self, _statement):
            return EmptyScalars()

    result = get_latest_fedwatch_factor_view(
        EmptySession(),
        as_of="2026-10-10T01:00:00+00:00",
        allowed_staleness_seconds=3600,
    )

    assert result["status"] == "unavailable"
    assert result["reason"] == "dws_factor_unavailable"
    assert result["source_health"]["actionable"] is False


def test_fedwatch_page_view_rechecks_staleness_from_factor_without_raw_rows() -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from apps.api.services.fedwatch_read_model_service import get_latest_fedwatch_factor_view

    row = SimpleNamespace(
        snapshot_id="factor-1",
        as_of=datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 10, 0, 1, tzinfo=timezone.utc),
        source_refs=[
            {
                "source_name": "CME FedWatch",
                "url": "https://www.cmegroup.com/fedwatch",
                "raw_artifact_ref": "raw/fedwatch/factor-1.json",
            }
        ],
        payload={
            "health": {
                "source_as_of": "2026-10-10T00:00:00+00:00",
                "quality_summary": {"meeting_count": 2},
            },
            "market_implied_path": {
                "next_meeting": {"meeting_date": "2026-12-16"},
                "year_end": {"meeting_date": "2026-12-16"},
                "meetings": [{"meeting_date": "2026-12-16"}],
            },
            "repricing": {"direction": "easing", "score": 0.6},
        },
    )

    class OneScalars:
        def first(self):
            return row

    class OneSession:
        def scalars(self, _statement):
            return OneScalars()

        def execute(self, _statement):
            class NoAttempt:
                def mappings(self):
                    return self

                def first(self):
                    return None

            return NoAttempt()

    result = get_latest_fedwatch_factor_view(
        OneSession(),
        as_of="2026-10-10T02:00:00+00:00",
        allowed_staleness_seconds=3600,
    )

    assert result["status"] == "degraded"
    assert result["source_health"]["status"] == "stale"
    assert result["repricing"]["direction"] is None
    assert result["source_refs"] == [{"source_name": "CME FedWatch", "url": "https://www.cmegroup.com/fedwatch"}]


def test_llm_detail_real_http_boundary_exposes_summary_not_prompt_or_raw_bodies() -> None:
    status_code, body = _response(
        {
            "audit_id": "fixture",
            "status": "success",
            "model_resolved": "gpt-test",
            "created_at": "2026-10-10T01:00:00+00:00",
            "prompt_messages": [{"role": "user", "content": "RAW_INPUT_FIXTURE"}],
            "input_payload": {"raw_payload": {"price": 123}},
            "raw_output": "MODEL_RAW_FIXTURE",
            "response_payload": {"opaque": True},
        },
        path="/api/llm/audits/fixture",
    )

    assert status_code == 200
    assert body == {
        "audit_id": "fixture",
        "status": "success",
        "model_resolved": "gpt-test",
        "created_at": "2026-10-10T01:00:00+00:00",
    }


def test_agent_inspection_and_report_inputs_keep_conclusions_but_remove_llm_bodies() -> None:
    inspection = {
        "trade_date": "2026-10-10",
        "agents": [
            {
                "agent_name": "synthesis_agent",
                "prompt": {"version": "v1", "messages": [{"content": "raw prompt"}]},
                "input": {"input_snapshot_ids": {"macro": "m1"}, "payload": {"raw": "input"}},
                "output": {
                    "summary": "研究结论保留",
                    "key_findings": ["利率驱动仍有效"],
                    "payload": {"input_payload": {"raw": True}},
                    "llm_raw_output": "raw model body",
                },
            }
        ],
    }
    projected_inspection = _project("/api/agent-analysis/inspect", inspection)
    agent = projected_inspection["agents"][0]
    assert agent["output"]["summary"] == "研究结论保留"
    assert agent["output"]["key_findings"] == ["利率驱动仍有效"]
    assert "messages" not in agent["prompt"]
    assert "payload" not in agent["input"]
    assert "payload" not in agent["output"]
    assert "llm_raw_output" not in agent["output"]

    report_inputs = {
        "report_id": "report-1",
        "deterministic_inputs": [{"input_id": "i1", "sections": ["macro"], "payload": {"raw": True}}],
        "agent_outputs": [
            {
                "agent_output_id": "a1",
                "summary": "报告研究结论",
                "llm_audit": {
                    "audit_id": "audit-1",
                    "status": "available",
                    "model_resolved": "gpt-test",
                    "prompt_messages": [{"content": "raw prompt"}],
                    "input_payload": {"raw": True},
                    "raw_output": "raw output",
                },
            }
        ],
    }
    projected_report = _project("/api/reports/report-1/analysis-inputs", report_inputs)
    assert "payload" not in projected_report["deterministic_inputs"][0]
    assert projected_report["agent_outputs"][0]["summary"] == "报告研究结论"
    assert projected_report["agent_outputs"][0]["llm_audit"] == {
        "audit_id": "audit-1",
        "status": "available",
        "model_resolved": "gpt-test",
    }


def _project(path: str, payload: dict) -> dict:
    from apps.api.services.page_data_boundary import project_http_payload

    result = project_http_payload(path, payload)
    assert isinstance(result, dict)
    return result


def test_page_news_read_model_preserves_acceptance_and_blocking_states(tmp_path: Path) -> None:
    from apps.api.services.page_news_read_model_service import get_page_news_monitor

    feature = tmp_path / "storage/features/news/2026-10-10/run-1/jin10_article_briefs.json"
    feature.parent.mkdir(parents=True)
    feature.write_text(
        json.dumps(
            {
                "as_of": "2026-10-10T01:00:00+00:00",
                "briefs": [
                    {"brief_id": "accepted", "source_url": "https://example/accepted", "headline": "Accepted", "status": "accepted"},
                    {"brief_id": "blocked", "source_url": "https://example/blocked", "headline": "Blocked", "status": "blocked"},
                    {"brief_id": "failed", "source_url": "https://example/failed", "headline": "Failed", "status": "failed"},
                    {
                        "brief_id": "unverified",
                        "source_url": "https://example/unverified",
                        "headline": "Unverified",
                        "data_quality": {"verification_status": "unverified"},
                    },
                    {"brief_id": "unknown", "source_url": "https://example/unknown", "headline": "Unknown"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = get_page_news_monitor(date="2026-10-10", project_root=tmp_path)
    items = {item["message_id"]: item for item in result["messages"]}

    assert result["accepted_count"] == 1
    assert result["blocked_count"] == 2
    assert result["actionable_count"] == 1
    assert items["accepted"]["accepted"] is True
    assert items["accepted"]["actionable"] is True
    assert items["blocked"]["blocked"] is True
    assert items["failed"]["blocked"] is True
    assert items["unverified"]["actionable"] is False
    assert items["unknown"]["decision_status"] == "unknown"
    assert items["unknown"]["actionable"] is False


def test_calendar_summary_reads_feature_snapshot_and_projects_only_saved_fields(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from apps.api.services.page_calendar_read_model_service import get_calendar_summary

    snapshot = tmp_path / "storage/features/snapshots/XAUUSD/2026-10-10/run-1/premarket_snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        json.dumps(
            {
                "snapshot_time": "2026-10-10T01:00:00+00:00",
                "news": {
                    "status": "available",
                    "data": {
                        "official_calendar": {
                            "status": "available",
                            "as_of": "2026-10-10T01:00:00+00:00",
                            "window_start_date": "2026-10-10",
                            "window_end_date": "2026-10-24",
                            "events": [
                                {
                                    "event_id": "fomc-1",
                                    "title": "FOMC meeting",
                                    "start_date": "2026-10-12",
                                    "verification_status": "official_confirmed",
                                    "source_refs": [
                                        {
                                            "source": "fomc_calendar",
                                            "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                                            "raw_path": "storage/raw/news/fomc.json",
                                        }
                                    ],
                                }
                            ],
                            "source_refs": [{"source": "fomc_calendar", "raw_path": "storage/raw/news/fomc.json"}],
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = get_calendar_summary(
        project_root=tmp_path,
        now=datetime(2026, 10, 10, 2, 0, tzinfo=timezone.utc),
    )

    assert result["status"] == "available"
    assert result["stats"]["total"] == 1
    event = result["events"][0]
    assert event["title"] == "FOMC meeting"
    assert event["actual"] is None and event["consensus"] is None and event["previous"] is None
    assert event["verification_status"] == "official_confirmed"
    assert event["source_refs"] == [
        {"source": "fomc_calendar", "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"}
    ]
    assert result["source_refs"] == [{"source": "fomc_calendar"}]


def test_calendar_summary_missing_and_stale_are_explicit(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from apps.api.services.page_calendar_read_model_service import get_calendar_summary

    missing = get_calendar_summary(project_root=tmp_path, now=datetime(2026, 10, 10, tzinfo=timezone.utc))
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "dws_calendar_unavailable"
    assert missing["events"] == []

    artifact = tmp_path / "storage/features/news/2026-10-01/run-1/official_calendar.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        json.dumps(
            {
                "status": "available",
                "as_of": "2026-10-01T00:00:00+00:00",
                "events": [{"event_id": "old", "title": "Old event", "start_date": "2026-10-11"}],
            }
        ),
        encoding="utf-8",
    )
    stale = get_calendar_summary(project_root=tmp_path, now=datetime(2026, 10, 10, tzinfo=timezone.utc))
    assert stale["status"] == "stale"
    assert stale["freshness"]["is_stale"] is True
    assert stale["reason"] == "source_stale"


def test_calendar_summary_does_not_invent_freshness_or_confirm_a_past_release(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from apps.api.services.page_calendar_read_model_service import get_calendar_summary

    artifact = tmp_path / "storage/features/news/2026-10-10/run-1/official_calendar.json"
    artifact.parent.mkdir(parents=True)
    payload = {
        "status": "available",
        "events": [{"title": "Scheduled release", "start_date": "2026-10-09", "actual": None}],
    }
    artifact.write_text(json.dumps(payload))
    result = get_calendar_summary(project_root=tmp_path, now=datetime(2026, 10, 10, tzinfo=UTC))
    assert result["status"] == "unavailable"
    assert result["reason"] == "source_timestamp_unavailable"
    assert result["events"][0]["release_state"] == "pending"
    assert result["stats"]["released"] == 0

    payload.update(as_of="2026-10-10T00:00:00Z", status="blocked", reason="quality_gate_failed")
    artifact.write_text(json.dumps(payload))
    result = get_calendar_summary(project_root=tmp_path, now=datetime(2026, 10, 10, tzinfo=UTC))
    assert result["status"] == "unavailable"
    assert result["reason"] == "quality_gate_failed"


def test_calendar_summary_route_is_registered_and_uses_the_dws_reader(monkeypatch) -> None:
    from apps.api.main import app
    from apps.api.routes import event_flow_routes

    expected = {"status": "unavailable", "reason": "dws_calendar_unavailable", "events": []}
    monkeypatch.setattr(event_flow_routes, "get_calendar_summary", lambda: expected)

    assert any(route.path == "/api/events/calendar-summary" for route in app.routes)
    assert event_flow_routes.api_event_calendar_summary() == expected


def test_non_json_api_boundary_blocks_unknown_file_routes_and_allows_safe_report_assets() -> None:
    blocked_status, blocked_body, blocked_type = _binary_response(
        path="/api/source-files/raw.pdf",
        media_type="application/pdf",
        body=b"raw-pdf",
    )
    allowed_status, allowed_body, allowed_type = _binary_response(
        path="/api/reports/report-1/asset/analysis_md/chart.png",
        media_type="image/png",
        body=b"rendered-image",
    )

    assert blocked_status == 403
    assert json.loads(blocked_body)["page_layer"] == "ADS"
    assert blocked_type.startswith("application/json")
    assert allowed_status == 200
    assert allowed_body == b"rendered-image"
    assert allowed_type == "image/png"
