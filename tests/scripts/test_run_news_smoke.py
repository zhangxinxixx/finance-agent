from __future__ import annotations

import json
from pathlib import Path

from apps.collectors.news.base import NewsCollectionResult, RawNewsItem
from scripts import run_news_smoke


def _raw_item(source_key: str, feed_key: str = "test") -> RawNewsItem:
    return RawNewsItem(
        source_key=source_key,
        source_name=source_key,
        source_type="official",
        feed_key=feed_key,
        title=f"{source_key} title",
        url=f"https://example.test/{source_key}/{feed_key}",
        domain="example.test",
        published_at="2026-06-11T00:00:00+00:00",
        fetched_at="2026-06-11T00:00:01+00:00",
        summary=None,
        source_country="US",
        source_language="en",
        event_type="macro_event",
        verification_status="official_confirmed",
        duplicate_key=f"news:{source_key}:{feed_key}",
        raw_payload={},
    )


def test_run_news_smoke_runs_requested_sources_and_prints_json_summary(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    calls: list[str] = []

    def collect_fed_rss(**kwargs) -> NewsCollectionResult:
        calls.append(f"fed_rss:{kwargs['retrieved_date']}")
        return NewsCollectionResult(
            source_key="fed_rss",
            status="success",
            items=[_raw_item("fed_rss", "press_releases"), _raw_item("fed_rss", "speeches_testimony")],
            source_refs=[
                {
                    "source_ref": "fed_rss:press_releases",
                    "source": "fed_rss",
                    "status": "ok",
                    "raw_path": "raw/news/fed_rss/2026-06-11/press.json",
                    "parsed_path": "parsed/news/fed_rss/2026-06-11/press.json",
                }
            ],
            warnings=["fed_rss:press_releases delayed"],
            unavailable_feeds=["speeches_testimony"],
        )

    monkeypatch.setattr(
        run_news_smoke,
        "_collector_registry",
        lambda: [("fed_rss", collect_fed_rss), ("gdelt_news", lambda **kwargs: None)],
    )

    exit_code = run_news_smoke.main(
        [
            "--sources",
            "fed_rss",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-11",
            "--run-id",
            "news-smoke-test",
        ]
    )

    assert exit_code == 0
    assert calls == ["fed_rss:2026-06-11"]

    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "news-smoke-test"
    assert payload["retrieved_date"] == "2026-06-11"
    assert payload["requested_sources"] == ["fed_rss"]
    assert payload["overall_status"] == "success"
    assert payload["results"] == [
        {
            "source_key": "fed_rss",
            "status": "success",
            "item_count": 2,
            "warning_count": 1,
            "unavailable_feeds": ["speeches_testimony"],
            "source_refs": {
                "count": 1,
                "status_counts": {"ok": 1},
                "sample": [
                    {
                        "source_ref": "fed_rss:press_releases",
                        "status": "ok",
                        "raw_path": "raw/news/fed_rss/2026-06-11/press.json",
                        "parsed_path": "parsed/news/fed_rss/2026-06-11/press.json",
                    }
                ],
            },
            "storage_root": str(tmp_path.resolve()),
            "run_id": "news-smoke-test",
            "retrieved_date": "2026-06-11",
        }
    ]


def test_run_news_smoke_runs_all_sources_in_registry_order(tmp_path: Path, monkeypatch, capsys) -> None:
    calls: list[str] = []

    def collector_for(source_key: str):
        def _collector(**kwargs) -> NewsCollectionResult:
            calls.append(source_key)
            return NewsCollectionResult(
                source_key=source_key,
                status="unavailable",
                items=[],
                source_refs=[{"source_ref": f"{source_key}:default", "source": source_key, "status": "empty"}],
                unavailable_feeds=["default"],
            )

        return _collector

    monkeypatch.setattr(
        run_news_smoke,
        "_collector_registry",
        lambda: [
            ("fed_rss", collector_for("fed_rss")),
            ("gdelt_news", collector_for("gdelt_news")),
            ("google_news_rss", collector_for("google_news_rss")),
        ],
    )

    exit_code = run_news_smoke.main(
        [
            "--sources",
            "all",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-11",
            "--run-id",
            "all-smoke-test",
        ]
    )

    assert exit_code == 0
    assert calls == ["fed_rss", "gdelt_news", "google_news_rss"]

    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_sources"] == ["fed_rss", "gdelt_news", "google_news_rss"]
    assert [item["source_key"] for item in payload["results"]] == calls
    assert payload["overall_status"] == "unavailable"


def test_run_news_smoke_marks_collector_exceptions_as_error(tmp_path: Path, monkeypatch, capsys) -> None:
    def ok_collector(**kwargs) -> NewsCollectionResult:
        return NewsCollectionResult(
            source_key="fed_rss",
            status="success",
            items=[_raw_item("fed_rss")],
            source_refs=[{"source_ref": "fed_rss:default", "source": "fed_rss", "status": "ok"}],
        )

    def broken_collector(**kwargs) -> NewsCollectionResult:
        raise RuntimeError("collector exploded")

    monkeypatch.setattr(
        run_news_smoke,
        "_collector_registry",
        lambda: [("fed_rss", ok_collector), ("gdelt_news", broken_collector)],
    )

    exit_code = run_news_smoke.main(
        [
            "--sources",
            "fed_rss,gdelt_news",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-11",
            "--run-id",
            "error-smoke-test",
        ]
    )

    assert exit_code == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_status"] == "error"
    error_summary = payload["results"][1]
    assert error_summary["source_key"] == "gdelt_news"
    assert error_summary["status"] == "error"
    assert error_summary["item_count"] == 0
    assert error_summary["warning_count"] == 1
    assert error_summary["unavailable_feeds"] == []
    assert error_summary["source_refs"]["status_counts"] == {"error": 1}
    assert error_summary["source_refs"]["sample"][0]["reason"] == "RuntimeError: collector exploded"


def test_run_news_smoke_passes_supported_runtime_controls_to_candidate_collectors(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    captured: dict[str, object] = {}

    def collect_gdelt_news(
        *,
        retrieved_date: str,
        storage_root: Path,
        query_groups: dict[str, str] | None = None,
        max_items_per_group: int = 50,
        request_timeout: float | None = None,
        request_proxy: str | None = None,
        trust_env: bool = True,
        timespan: str = "12h",
        rate_limit_cooldown_seconds: int = 900,
    ) -> NewsCollectionResult:
        captured["retrieved_date"] = retrieved_date
        captured["storage_root"] = storage_root
        captured["query_groups"] = query_groups
        captured["max_items_per_group"] = max_items_per_group
        captured["request_timeout"] = request_timeout
        captured["request_proxy"] = request_proxy
        captured["trust_env"] = trust_env
        captured["timespan"] = timespan
        captured["rate_limit_cooldown_seconds"] = rate_limit_cooldown_seconds
        return NewsCollectionResult(
            source_key="gdelt_news",
            status="success",
            items=[_raw_item("gdelt_news", "yen_intervention")],
            source_refs=[{"source_ref": "gdelt_news:yen_intervention", "source": "gdelt_news", "status": "available"}],
        )

    monkeypatch.setattr(
        run_news_smoke,
        "_collector_registry",
        lambda: [("gdelt_news", collect_gdelt_news)],
    )

    exit_code = run_news_smoke.main(
        [
            "--sources",
            "gdelt_news",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-11",
            "--run-id",
            "gdelt-smoke-controls",
            "--query-groups",
            "yen_intervention,missing_group",
            "--max-items-per-group",
            "7",
            "--request-timeout-seconds",
            "3.5",
            "--proxy-url",
            "http://127.0.0.1:7890",
            "--no-trust-env",
            "--timespan",
            "1h",
            "--rate-limit-cooldown-seconds",
            "60",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "retrieved_date": "2026-06-11",
        "storage_root": tmp_path,
        "query_groups": {
            "yen_intervention": '(USDJPY OR "USD/JPY" OR "yen intervention" OR BOJ OR "Bank of Japan" OR "Japan Ministry of Finance")',
        },
        "max_items_per_group": 7,
        "request_timeout": 3.5,
        "request_proxy": "http://127.0.0.1:7890",
        "trust_env": False,
        "timespan": "1h",
        "rate_limit_cooldown_seconds": 60,
    }

    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_query_groups"] == ["yen_intervention", "missing_group"]
    assert payload["proxy_url"] == "http://127.0.0.1:7890"
    assert payload["trust_env"] is False


def test_run_news_smoke_does_not_fallback_to_default_queries_when_groups_do_not_match(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    calls: list[str] = []

    def collect_google_news_rss(**kwargs) -> NewsCollectionResult:
        calls.append("google_news_rss")
        return NewsCollectionResult(
            source_key="google_news_rss",
            status="success",
            items=[_raw_item("google_news_rss", "gold_macro")],
            source_refs=[
                {"source_ref": "google_news_rss:gold_macro", "source": "google_news_rss", "status": "available"}
            ],
        )

    monkeypatch.setattr(
        run_news_smoke,
        "_collector_registry",
        lambda: [("google_news_rss", collect_google_news_rss)],
    )
    monkeypatch.setattr(
        run_news_smoke,
        "_query_group_registry",
        lambda: {"google_news_rss": {"gold_macro": "gold XAU", "middle_east": "Iran Hormuz"}},
    )

    exit_code = run_news_smoke.main(
        [
            "--sources",
            "google_news_rss",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-11",
            "--run-id",
            "google-smoke-invalid-groups",
            "--query-groups",
            "middle_east_hormuz,gold_yields",
        ]
    )

    assert exit_code == 0
    assert calls == []

    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_status"] == "unavailable"
    assert payload["results"][0]["source_key"] == "google_news_rss"
    assert payload["results"][0]["status"] == "unavailable"
    assert payload["results"][0]["item_count"] == 0
    assert payload["results"][0]["warning_count"] == 1
    assert payload["results"][0]["unavailable_feeds"] == ["middle_east_hormuz", "gold_yields"]
    assert payload["results"][0]["source_refs"]["status_counts"] == {"unavailable": 1}
    assert payload["results"][0]["source_refs"]["sample"][0]["reason_code"] == "invalid_query_groups"


def test_run_news_smoke_drops_unsupported_runtime_controls_for_collectors(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    captured: dict[str, object] = {}

    def collect_fed_rss(*, retrieved_date: str, storage_root: Path) -> NewsCollectionResult:
        captured["retrieved_date"] = retrieved_date
        captured["storage_root"] = storage_root
        return NewsCollectionResult(
            source_key="fed_rss",
            status="success",
            items=[_raw_item("fed_rss")],
            source_refs=[{"source_ref": "fed_rss:default", "source": "fed_rss", "status": "ok"}],
        )

    monkeypatch.setattr(
        run_news_smoke,
        "_collector_registry",
        lambda: [("fed_rss", collect_fed_rss)],
    )

    exit_code = run_news_smoke.main(
        [
            "--sources",
            "fed_rss",
            "--storage-root",
            str(tmp_path),
            "--retrieved-date",
            "2026-06-11",
            "--run-id",
            "fed-smoke-controls",
            "--query-groups",
            "gold_macro",
            "--max-items-per-group",
            "5",
            "--request-timeout-seconds",
            "2.0",
            "--timespan",
            "1h",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "retrieved_date": "2026-06-11",
        "storage_root": tmp_path,
    }

    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_query_groups"] == ["gold_macro"]
