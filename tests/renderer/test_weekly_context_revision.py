from __future__ import annotations

from apps.renderer.contracts import WeeklyContextRevisionPayload
from apps.renderer.markdown.weekly_context_revision import (
    build_weekly_context_revision_payload,
    render_weekly_context_revision_analysis_markdown,
    render_weekly_context_revision_source_markdown,
)


def _input_snapshot(*, baseline_quality: str = "accepted") -> dict:
    return {
        "status": "ready" if baseline_quality == "accepted" else "degraded",
        "asset": "XAUUSD",
        "trade_date": "2026-07-19",
        "context_as_of": "2026-07-19T11:14:10+00:00",
        "anchor": {
            "article_id": "224965",
            "report_date": "2026-07-18",
            "run_id": "224965",
            "title": "黄金短期难破僵局，期权数据与主力动向暗示底部夯实",
            "baseline_quality_status": baseline_quality,
            "baseline_artifact_refs": [
                {
                    "artifact_type": "jin10_weekly_analysis",
                    "path": "outputs/jin10/2026-07-18/224965/agent_analysis_report.json",
                }
            ],
        },
        "input_snapshot_ids": {
            "weekly_baseline": "outputs/jin10/2026-07-18/224965/agent_analysis_report.json",
            "premarket_snapshot": (
                "features/snapshots/XAUUSD/2026-07-19/context-run/premarket_snapshot.json"
            ),
        },
        "freshness": {
            "baseline": {"as_of": "2026-07-18", "status": "available"},
            "price": {"as_of": "2026-07-19T11:14:10+00:00", "status": "available"},
            "rates": {"as_of": "2026-07-17", "status": "available"},
            "options": {"as_of": "2026-07-17", "status": "available"},
            "positioning": {"as_of": "2026-07-14", "status": "available"},
            "oil": {"as_of": "2026-07-17", "status": "available"},
            "news": {"as_of": "2026-07-19T11:14:14+00:00", "status": "available"},
        },
        "baseline_claims": [
            {
                "claim_id": "overall_thesis",
                "category": "overall_thesis",
                "claim": "期权数据与主力动向暗示底部夯实。",
                "source_path": "one_line_conclusion",
            },
            {
                "claim_id": "market_stage",
                "category": "market_stage",
                "claim": "利率压制态",
                "source_path": "market_stage.label",
            },
        ],
        "new_evidence": [
            {"evidence_id": "price", "category": "price", "status": "available", "value": 4016.55},
            {"evidence_id": "rates", "category": "rates", "status": "available", "value": 2.35},
            {"evidence_id": "options", "category": "options", "status": "available", "value": 4000},
        ],
        "confirmation_matrix": {
            "price": {
                "status": "observed",
                "basis": "point_quote",
                "current_price": 4016.55,
                "as_of": "2026-07-19T11:14:10+00:00",
            },
            "rates": {
                "status": "confirmed",
                "real_10y": 2.35,
                "us10y": 4.57,
                "dxy": 100.755,
                "as_of": "2026-07-17",
            },
            "options": {
                "status": "confirmed",
                "report_status": "PRELIM",
                "trade_date": "2026-07-17",
                "primary_wall": 4000,
                "gamma_zero": 4126.43,
            },
            "macro": {"status": "confirmed"},
            "geopolitical": {"status": "observed"},
        },
        "positioning_check": {
            "status": "confirmed",
            "as_of": "2026-07-14",
            "noncomm_net": 120779.0,
            "noncomm_net_prev": 116161.0,
        },
        "dominant_transmission_chain": {
            "status": "confirmed",
            "label": "地缘风险 -> 油价 -> 通胀预期 -> 实际利率 -> 黄金",
            "dominant_driver": "oil_inflation_rate_pressure",
        },
        "scenario_updates": [],
        "watch_items": [{"label": "4000 是否守住", "status": "active"}],
        "revision_risk": {
            "level": "monitor",
            "reason": "价格只有点报价，尚不能代替 4H 或日线收盘确认。",
            "quality_flags": [],
        },
        "source_refs": [{"source": "cftc", "source_ref": "cot:2026-07-14"}],
        "quality_flags": [] if baseline_quality == "accepted" else ["baseline_needs_review"],
        "warnings": [],
    }


def test_weekly_revision_payload_keeps_claim_diff_and_freshness_machine_readable() -> None:
    payload = build_weekly_context_revision_payload(_input_snapshot(), run_id="revision-run")

    validated = WeeklyContextRevisionPayload.model_validate(payload.model_dump(mode="json"))
    assert validated.report_type == "weekly_context_revision"
    assert validated.anchor.article_id == "224965"
    assert validated.quality_status == "accepted"
    assert validated.publish_allowed is True
    assert {item.action for item in validated.claim_revisions} <= {
        "maintain",
        "strengthen",
        "weaken",
        "invalidate",
        "pending",
    }
    assert validated.freshness["options"]["as_of"] == "2026-07-17"
    assert validated.positioning_check["as_of"] == "2026-07-14"


def test_weekly_revision_never_promotes_needs_review_baseline() -> None:
    payload = build_weekly_context_revision_payload(
        _input_snapshot(baseline_quality="needs_review"),
        run_id="revision-run",
    )

    assert payload.quality_status == "needs_review"
    assert payload.publish_allowed is False
    assert payload.publication_status == "observe"
    assert "baseline_needs_review" in payload.revision_risk["quality_flags"]


def test_weekly_revision_markdown_is_rendered_from_validated_payload() -> None:
    snapshot = _input_snapshot()
    payload = build_weekly_context_revision_payload(snapshot, run_id="revision-run")

    source_markdown = render_weekly_context_revision_source_markdown(snapshot)
    analysis_markdown = render_weekly_context_revision_analysis_markdown(payload.model_dump(mode="json"))

    assert "224965" in source_markdown
    assert "2026-07-14" in source_markdown
    assert "基线结论修正" in analysis_markdown
    assert "价格确认" in analysis_markdown
    assert "利率确认" in analysis_markdown
    assert "期权确认" in analysis_markdown
    assert "仅供观察" not in analysis_markdown
