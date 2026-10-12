from __future__ import annotations

from datetime import UTC, datetime

from apps.features.positioning.formal_snapshot import build_cot_positioning_snapshot


AS_OF = datetime(2026, 9, 5, tzinfo=UTC)
COMBINED_URL = "https://www.cftc.gov/files/dea/history/com_disagg_txt_2026.zip"
FUTURES_ONLY_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip"


def _rows(*, retrieved_at: object, raw_path: str) -> list[dict[str, object]]:
    common = {
        "report_type": "combined",
        "source": "cftc",
        "source_url": COMBINED_URL,
        "retrieved_at": retrieved_at,
        "raw_path": raw_path,
        "managed_money_long": 120_000,
        "managed_money_short": 30_000,
        "producer_long": 50_000,
        "producer_short": 70_000,
        "swap_long": 80_000,
        "swap_short": 90_000,
        "other_long": 20_000,
        "other_short": 25_000,
        "open_interest": 600_000,
    }
    latest = {**common, "date": "2026-09-01"}
    previous = {
        **common,
        "date": "2026-08-25",
        "managed_money_long": 110_000,
        "managed_money_short": 25_000,
        "open_interest": 590_000,
    }
    return [latest, previous]


def _source_ref(
    *,
    retrieved_at: object,
    raw_path: str,
    report_type: str = "combined",
    source_url: str = COMBINED_URL,
) -> dict[str, object]:
    return {
        "source": "cftc",
        "source_url": source_url,
        "raw_path": raw_path,
        "raw_archive_path": "raw/positioning/cot.zip",
        "report_type": report_type,
        "retrieved_at": retrieved_at,
    }


def test_full_contract_does_not_substitute_as_of_for_missing_retrieval() -> None:
    result = build_cot_positioning_snapshot(
        candidates=_rows(retrieved_at="", raw_path="raw/positioning/cot.json"),
        source_refs=[
            _source_ref(retrieved_at="", raw_path="raw/positioning/cot.json"),
        ],
        report_type="combined",
        as_of=AS_OF,
    )

    assert result.readiness == "blocked"
    assert result.freshness_status == "missing"
    assert "retrieval_time_missing_or_naive" in result.reason_codes
    assert result.source_refs[0].qualification_reason == "retrieval_time_missing_or_naive"


def test_full_contract_rejects_retrieval_after_as_of() -> None:
    future = "2026-09-05T01:00:00Z"
    result = build_cot_positioning_snapshot(
        candidates=_rows(retrieved_at=future, raw_path="raw/positioning/cot.json"),
        source_refs=[
            _source_ref(retrieved_at=future, raw_path="raw/positioning/cot.json"),
        ],
        report_type="combined",
        as_of=AS_OF,
    )

    assert result.readiness == "blocked"
    assert result.freshness_status == "missing"
    assert result.alignment_status == "misaligned"
    assert "retrieval_time_after_as_of" in result.reason_codes
    assert result.source_refs[0].qualification_reason == "retrieval_time_after_as_of"


def test_full_contract_does_not_authorize_rows_from_another_raw_path() -> None:
    result = build_cot_positioning_snapshot(
        candidates=_rows(retrieved_at=AS_OF, raw_path="raw/positioning/bad.json"),
        source_refs=[
            _source_ref(retrieved_at=AS_OF, raw_path="raw/positioning/good.json"),
        ],
        report_type="combined",
        as_of=AS_OF,
    )

    assert result.readiness == "blocked"
    assert result.freshness_status == "missing"
    assert "candidate_source_lineage_not_eligible" in result.reason_codes
    assert result.source_refs[0].qualification_reason == "eligible"


def test_full_contract_does_not_relabel_futures_only_lineage_as_combined() -> None:
    result = build_cot_positioning_snapshot(
        candidates=_rows(retrieved_at=AS_OF, raw_path="raw/positioning/futures.json"),
        source_refs=[
            _source_ref(
                retrieved_at=AS_OF,
                raw_path="raw/positioning/futures.json",
                report_type="futures_only",
                source_url=FUTURES_ONLY_URL,
            ),
        ],
        report_type="combined",
        as_of=AS_OF,
    )

    assert result.readiness == "blocked"
    assert result.freshness_status == "missing"
    assert "candidate_source_lineage_not_eligible" in result.reason_codes
