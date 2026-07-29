from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from apps.features.positioning.formal_snapshot import COTSourceReference, build_cot_snapshot


AS_OF = datetime(2026, 7, 24, 21, 0, tzinfo=UTC)


def _cftc_url(year: int = 2026) -> str:
    return f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"


def _candidate(
    *,
    report_date: str = "2026-07-21",
    retrieved_at: datetime | str = "2026-07-24T20:00:00Z",
    value: float = 116_161.0,
    raw_path: str = "raw/positioning/2026-07-24/cot_gold.json",
    **overrides: object,
) -> dict[str, object]:
    return {
        "symbol": "COT_GOLD_noncomm_net",
        "date": report_date,
        "value": value,
        "source": "cftc",
        "source_url": _cftc_url(),
        "retrieved_at": retrieved_at,
        "raw_path": raw_path,
        **overrides,
    }


def test_builds_exact_official_managed_money_contract() -> None:
    result = build_cot_snapshot(candidates=[_candidate()], as_of=AS_OF)

    assert result.schema_version == "cot_snapshot.v1"
    assert result.as_of == AS_OF
    assert result.readiness == "ready"
    assert result.managed_money_net.model_dump(mode="json") == {
        "series_id": "GOLD_COT",
        "metric_kind": "managed_money_net_contracts",
        "value": 116_161.0,
        "unit": "contracts",
        "report_date": "2026-07-21",
        "expected_frequency": "weekly",
        "freshness_status": "fresh",
        "quality_status": "accepted",
        "alignment_status": "aligned",
        "source_refs": [{
            "source": "cftc", "reference": _cftc_url(),
            "raw_path": "raw/positioning/2026-07-24/cot_gold.json",
            "retrieved_at": "2026-07-24T20:00:00Z", "qualification_reason": "eligible",
        }],
    }


def test_selects_latest_known_report_and_deduplicates_identical_latest_values() -> None:
    earlier = _candidate(report_date="2026-07-14", value=100_000)
    latest = _candidate()
    duplicate = _candidate()

    result = build_cot_snapshot(candidates=[earlier, latest, duplicate], as_of=AS_OF)

    assert result.managed_money_net.report_date.isoformat() == "2026-07-21"
    assert result.managed_money_net.value == 116_161
    assert len(result.managed_money_net.source_refs) == 1


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"symbol": "COT_GOLD_commercial_net"}, "wrong_symbol"),
        ({"source": "jin10"}, "wrong_source"),
        ({"source_url": "https://example.test/cot"}, "wrong_source_url"),
        ({"source_url": "https://www.cftc.gov.evil.test/files/dea/history/fut_disagg_txt_2026.zip"}, "wrong_source_url"),
        ({"raw_path": ""}, "raw_path_missing"),
        ({"retrieved_at": "2026-07-24T20:00:00"}, "retrieval_time_missing_or_naive"),
        ({"retrieved_at": "2026-07-25T20:00:00Z"}, "retrieval_time_after_as_of"),
        ({"report_date": "2026-07-25"}, "report_date_after_as_of"),
        ({"value": float("nan")}, "value_invalid"),
    ],
)
def test_invalid_identity_lineage_time_and_value_fail_closed(
    overrides: dict[str, object], reason: str
) -> None:
    result = build_cot_snapshot(candidates=[_candidate(**overrides)], as_of=AS_OF)

    observation = result.managed_money_net
    assert result.readiness == "blocked"
    assert observation.value is None
    assert observation.freshness_status == "missing"
    assert observation.quality_status == "blocked"
    assert observation.source_refs[0].qualification_reason == reason


def test_accepts_only_exact_cftc_host_and_yearly_history_path() -> None:
    result = build_cot_snapshot(
        candidates=[_candidate(source_url=_cftc_url(2027))],
        as_of=AS_OF,
    )

    assert result.readiness == "ready"


def test_eligible_typed_reference_cannot_claim_non_cftc_lineage() -> None:
    with pytest.raises(ValueError, match="official CFTC raw lineage"):
        COTSourceReference(
            source="jin10",
            reference="https://example.test/cot.zip",
            raw_path="raw/cot.json",
            retrieved_at=AS_OF,
            qualification_reason="eligible",
        )


def test_missing_or_naive_retrieval_uses_query_lineage_not_forged_candidate_ref() -> None:
    result = build_cot_snapshot(candidates=[_candidate(retrieved_at="")], as_of=AS_OF)

    ref = result.managed_money_net.source_refs[0]
    assert ref.source == "cot_snapshot_query"
    assert ref.reference == "query://COT_GOLD/noncomm_net"
    assert ref.retrieved_at == AS_OF


@pytest.mark.parametrize(
    "second",
    [_candidate(value=100_001), _candidate(source_url=_cftc_url(2027))],
)
def test_ambiguous_latest_value_or_source_fails_closed(second: dict[str, object]) -> None:
    first = _candidate(value=100_000)

    result = build_cot_snapshot(candidates=[first, second], as_of=AS_OF)

    assert result.readiness == "blocked"
    assert result.managed_money_net.source_refs[0].qualification_reason == "ambiguous_latest_cot_candidate"


def test_stale_observe_then_ancient_blocked() -> None:
    stale = _candidate(report_date="2026-07-11")
    stale_result = build_cot_snapshot(candidates=[stale], as_of=AS_OF)
    ancient = _candidate(report_date="2026-07-01")
    ancient_result = build_cot_snapshot(candidates=[ancient], as_of=AS_OF)

    assert (stale_result.readiness, stale_result.managed_money_net.freshness_status, stale_result.managed_money_net.quality_status) == ("observe", "stale", "observe")
    assert ancient_result.readiness == "blocked"
    assert ancient_result.managed_money_net.value == 116_161
    assert ancient_result.managed_money_net.freshness_status == "stale"
    assert ancient_result.managed_money_net.quality_status == "blocked"
    assert ancient_result.managed_money_net.alignment_status == "aligned"


def test_identity_failure_is_unknown_alignment_but_future_knowledge_is_misaligned() -> None:
    wrong_source = build_cot_snapshot(
        candidates=[_candidate(source="jin10")], as_of=AS_OF
    )
    future_retrieval = build_cot_snapshot(
        candidates=[_candidate(retrieved_at="2026-07-25T20:00:00Z")], as_of=AS_OF
    )

    assert wrong_source.managed_money_net.alignment_status == "unknown"
    assert future_retrieval.managed_money_net.alignment_status == "misaligned"


def test_empty_input_keeps_query_lineage_and_aware_as_of_is_required() -> None:
    result = build_cot_snapshot(candidates=[], as_of=AS_OF)

    assert result.readiness == "blocked"
    assert result.managed_money_net.source_refs[0].reference == "query://COT_GOLD/noncomm_net"
    with pytest.raises(ValueError, match="timezone-aware"):
        build_cot_snapshot(candidates=[], as_of=datetime(2026, 7, 24, 21, 0))


def test_same_input_is_stable_and_does_not_mutate_input() -> None:
    candidates = [_candidate(), _candidate(report_date="2026-07-14", value=100_000)]
    before = copy.deepcopy(candidates)

    results = [build_cot_snapshot(candidates=candidates, as_of=AS_OF) for _ in range(100)]

    assert len({result.model_dump_json() for result in results}) == 1
    assert candidates == before
