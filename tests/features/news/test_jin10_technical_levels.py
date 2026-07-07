from __future__ import annotations

import json
from pathlib import Path

from apps.features.news.jin10_technical_levels import (
    archive_jin10_technical_levels,
    extract_jin10_technical_levels,
)


RAW_REPORT = {
    "article_id": "301",
    "document_id": "jin10-2026-06-11-301",
    "run_id": "301",
    "title": "黄金日内关键点位图解-金十数据VIP",
    "trade_date": "2026-06-11",
    "report_type": "technical_levels",
    "source_url": "https://svip.jin10.com/news/301",
    "article_markdown": (
        "# 黄金日内关键点位图解\n\n"
        "XAUUSD 维持震荡，VAH 3378.5，VAL 3332.0，POC 3356.2。"
        "若站稳3380上方，则上看3402阻力；跌破3330则测试3312-3320支撑区间。"
    ),
    "generated_from": {
        "article_context": {
            "key_sentences": [
                "XAUUSD 维持震荡，VAH 3378.5，VAL 3332.0，POC 3356.2。",
                "若站稳3380上方，则上看3402阻力；跌破3330则测试3312-3320支撑区间。",
            ],
            "chart_summaries": [
                "VLM markdown: 黄金筹码峰集中在3350-3360区域，图中未给出明确触发条件。",
            ],
        }
    },
    "source_refs": [
        {
            "source": "jin10_external",
            "asset_type": "report_md",
            "path": "/tmp/finance-agent/jin10-reports/2026-06-11/technical_levels/301/report.md",
            "source_url": "https://svip.jin10.com/news/301",
        }
    ],
}


def test_extract_jin10_technical_levels_from_report_text_and_vlm_markdown() -> None:
    extraction = extract_jin10_technical_levels(
        raw_article_report=RAW_REPORT,
        artifact_paths={
            "raw_article_report": "storage/outputs/jin10/2026-06-11/301/raw_article_report.json",
        },
        fetched_at="2026-06-11T09:30:00+00:00",
    )

    data = extraction.to_dict()
    items = data["items"]
    by_type = {item["level_type"]: item for item in items}

    assert data["source_key"] == "jin10_technical_levels"
    assert data["status"] == "ok"
    assert data["data_quality"]["report_type"] == "technical_levels"
    assert data["data_quality"]["level_count"] == 6
    assert {"VAH", "VAL", "POC", "resistance", "support", "volume_profile_peak"} <= set(by_type)

    assert by_type["VAH"]["symbol"] == "XAUUSD"
    assert by_type["VAH"]["price"] == 3378.5
    assert by_type["VAH"]["range"] is None
    assert by_type["VAH"]["verification_status"] == "single_source"
    assert by_type["VAH"]["provider_role"] == "supplemental_source"
    assert by_type["VAH"]["source_refs"]

    assert by_type["support"]["price"] is None
    assert by_type["support"]["range"] == {"low": 3312.0, "high": 3320.0}
    assert "跌破3330" in by_type["support"]["trigger_condition"]
    assert "3312-3320支撑区间" in by_type["support"]["evidence_text"]

    assert by_type["resistance"]["price"] == 3402.0
    assert by_type["resistance"]["range"] is None
    assert "站稳3380上方" in by_type["resistance"]["trigger_condition"]

    assert by_type["volume_profile_peak"]["range"] == {"low": 3350.0, "high": 3360.0}
    assert by_type["volume_profile_peak"]["trigger_condition"] == ""
    assert 0 < by_type["volume_profile_peak"]["confidence"] < 1


def test_extract_jin10_technical_levels_leaves_missing_fields_empty_without_inventing_numbers() -> None:
    extraction = extract_jin10_technical_levels(
        raw_article_report={
            **RAW_REPORT,
            "article_markdown": "黄金上方压力仍然明显，但正文未给出具体价位。",
            "generated_from": {"article_context": {"chart_summaries": ["VLM markdown: 阻力区域偏强，未标注价格。"]}},
        },
        fetched_at="2026-06-11T09:30:00+00:00",
    )

    data = extraction.to_dict()

    assert data["status"] == "empty"
    assert data["items"] == []
    assert data["warnings"] == ["No deterministic technical levels with explicit prices or ranges were found."]


def test_archive_jin10_technical_levels_writes_feature_artifact(tmp_path: Path) -> None:
    extraction = extract_jin10_technical_levels(
        raw_article_report=RAW_REPORT,
        fetched_at="2026-06-11T09:30:00+00:00",
    )

    artifact_path = archive_jin10_technical_levels(
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        run_id="301",
        extraction=extraction,
    )

    assert artifact_path == "features/news/2026-06-11/301/technical_levels.json"
    payload = json.loads((tmp_path / artifact_path).read_text(encoding="utf-8"))
    assert payload["items"][0]["verification_status"] == "single_source"
