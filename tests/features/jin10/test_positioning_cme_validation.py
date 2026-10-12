from __future__ import annotations

from apps.features.jin10.positioning_cme_validation import (
    extract_positioning_oi_changes,
    validate_positioning_against_cme,
)


def test_positioning_rows_extract_and_match_cme_oi_changes() -> None:
    report_rows = extract_positioning_oi_changes(
        [
            {
                "page_no": 10,
                "markdown": (
                    "## 黄金持仓报告\n\n期权布局变化（对应AUG26期货价格）：\n"
                    "4200 看涨期权-36手，看跌期权-2手\n"
                    "4150 看涨期权+171手，看跌期权-1手"
                ),
            }
        ]
    )
    cme_payload = {
        "trade_date": "2026-07-21",
        "detail_rows": [
            {"product": "OG", "expiry": "AUG26", "strike": 4200, "option_type": "CALL", "oi_change": -36},
            {"product": "OG", "expiry": "AUG26", "strike": 4200, "option_type": "PUT", "oi_change": -2},
            {"product": "OG", "expiry": "AUG26", "strike": 4150, "option_type": "CALL", "oi_change": 171},
            {"product": "OG", "expiry": "AUG26", "strike": 4150, "option_type": "PUT", "oi_change": -1},
        ],
    }

    artifact = validate_positioning_against_cme(
        article_id="225350",
        report_date="2026-07-22",
        report_rows=report_rows,
        cme_payload=cme_payload,
        report_source_ref={"source": "jin10"},
        cme_source_ref={"source": "cme"},
    )

    assert len(report_rows) == 2
    assert artifact["validation_status"] == "confirmed"
    assert artifact["summary"] == {
        "comparison_count": 4,
        "matched_count": 4,
        "mismatched_count": 0,
        "missing_count": 0,
        "match_rate": 1.0,
    }
