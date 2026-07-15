from __future__ import annotations

import math

import pytest

from apps.analysis.strategy.recompute_request_resolution import (
    RecomputeRequestValidationError,
    resolve_recompute_request,
    validate_recompute_request,
)


def _request(**overrides):
    value = {
        "request_id": "request-1",
        "schema_name": "live_strategy_recompute_request",
        "schema_version": "live_strategy_recompute_request.v1",
        "requested_action": "recompute_live_strategy",
        "event_id": "event-1",
        "event_hash": "event-hash",
        "observation_hash": "observation-hash",
        "source_key": "jin10_report",
        "trade_date": "2026-07-18",
        "published_at": "2026-07-18T08:00:00Z",
        "evidence_level": "full",
        "quality_status": "allowed",
        "dispatch_status": "pending",
        "reason_codes": [],
        "detected_at": "2026-07-18T08:01:00+00:00",
        "created_at": "2026-07-18T08:02:00Z",
        "source_refs": [{"source_ref": "event:source-1"}],
        "raw_refs": [{"path": "raw/jin10/index.json"}],
        "parsed_refs": [{"path": "parsed/jin10/index.json"}],
        "output_refs": [{"path": "outputs/jin10/report.json"}],
    }
    value.update(overrides)
    return value


def _event(event_id="event-1", **overrides):
    value = {
        "event_id": event_id,
        "source_refs": [{"source_ref": "event:source-1"}],
        "raw_refs": [{"path": "raw/jin10/index.json"}],
        "parsed_refs": [{"path": "parsed/jin10/index.json"}],
        "output_refs": [{"path": "outputs/jin10/report.json"}],
        "title": "Not used for resolution",
    }
    value.update(overrides)
    return value


def test_valid_request_normalizes_timestamps_and_exact_id_is_eligible() -> None:
    result = resolve_recompute_request(_request(), [_event()])

    assert validate_recompute_request(_request())["created_at"] == "2026-07-18T08:02:00Z"
    assert result.to_dict() == {
        "schema_version": "live_strategy_recompute_resolution.v1",
        "request_id": "request-1",
        "resolution_status": "eligible",
        "reason_codes": ["exact_event_id_match"],
        "resolved_event_flow_id": "event-1",
        "matched_event_ids": ["event-1"],
    }


def test_blocked_request_stays_blocked_even_with_an_exact_event() -> None:
    result = resolve_recompute_request(_request(dispatch_status="blocked"), [_event()])

    assert result.resolution_status == "blocked"
    assert result.resolved_event_flow_id is None
    assert result.reason_codes == ("request_dispatch_blocked",)


def test_duplicate_exact_ids_are_explicitly_ambiguous() -> None:
    result = resolve_recompute_request(_request(), [_event(), _event()])

    assert result.resolution_status == "unresolved"
    assert result.reason_codes == ("ambiguous_exact_event_id",)
    assert result.resolved_event_flow_id is None


def test_unique_lineage_match_requires_an_exact_structured_reference() -> None:
    request = _request(event_id="missing-event")
    result = resolve_recompute_request(request, [_event("different-event")])

    assert result.resolution_status == "eligible"
    assert result.reason_codes == ("unique_lineage_ref_match",)
    assert result.resolved_event_flow_id == "different-event"


def test_real_event_flow_shape_accepts_id_and_only_source_refs() -> None:
    request = _request(event_id="missing-event")
    result = resolve_recompute_request(
        request,
        [{"id": "event-flow-1", "source_refs": [{"source_ref": "event:source-1"}]}],
    )

    assert result.resolution_status == "eligible"
    assert result.reason_codes == ("unique_lineage_ref_match",)
    assert result.resolved_event_flow_id == "event-flow-1"


def test_real_event_flow_raw_path_matches_request_path_without_field_guessing() -> None:
    request = _request(
        event_id="missing-event",
        source_refs=[],
        raw_refs=[{"path": "raw/news/fed/2026-07-18/release.json"}],
        parsed_refs=[],
        output_refs=[],
    )
    result = resolve_recompute_request(
        request,
        [
            {
                "id": "event-flow-raw-1",
                "source_refs": [
                    {"raw_path": "storage/raw/news/fed/2026-07-18/release.json"}
                ],
            }
        ],
    )

    assert result.resolution_status == "eligible"
    assert result.reason_codes == ("unique_lineage_ref_match",)
    assert result.resolved_event_flow_id == "event-flow-raw-1"


def test_lineage_ambiguity_and_title_similarity_do_not_resolve() -> None:
    request = _request(event_id="missing-event")
    ambiguous = resolve_recompute_request(request, [_event("event-2"), _event("event-3")])
    title_only = resolve_recompute_request(
        request,
        [_event("event-4", source_refs=[], raw_refs=[], parsed_refs=[], output_refs=[], title="same title")],
    )

    assert ambiguous.reason_codes == ("ambiguous_lineage_ref_match",)
    assert ambiguous.resolved_event_flow_id is None
    assert title_only.reason_codes == ("event_flow_event_not_found",)
    assert title_only.resolved_event_flow_id is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_at", "2026-07-18T08:02:00"),
        ("source_key", ""),
        ("raw_refs", [{"path": math.nan}]),
        ("parsed_refs", ["not-a-ref"]),
        ("reason_codes", [""]),
    ],
)
def test_malformed_or_non_json_request_is_rejected(field: str, value: object) -> None:
    with pytest.raises(RecomputeRequestValidationError):
        validate_recompute_request(_request(**{field: value}))
