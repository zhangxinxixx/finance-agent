from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.cme_options_regime import (
    CMEOptionsRegime,
    CMEOptionsRegimeSnapshot,
    CMEOptionsRegimeSnapshotInput,
    adapt_options_analysis_to_cme_options_regime,
    build_cme_options_regime_snapshot,
)


FEATURE_ID = f"feature_snapshot.v2:{'a' * 64}"
AS_OF = datetime(2026, 7, 29, 21, 0, tzinfo=UTC)


def _options_output(*, status: str = "FINAL", net_gex: float = -120.0) -> dict:
    return {
        "version": "1.0",
        "trade_date": "2026-07-29",
        "generated_at": "2026-07-29T20:30:00Z",
        "snapshot_id": "options:2026-07-29:og-test",
        "data_source": {
            "report_date": "2026-07-29",
            "status": status,
            "source_url": "https://www.cmegroup.com/daily_bulletin/Section64.pdf",
            "product": "OG",
            "expiries": ["AUG26", "SEP26"],
            "input_snapshot_ids": {"parsed_cme": "cme:2026-07-29:abc"},
        },
        "parameters": {
            "report_p0": 4100.0,
            "report_p0_source": "CME settlement",
            "report_p0_timestamp": "2026-07-29T20:00:00Z",
            "model": "black-76",
            "used_real_gex": True,
            "model_f": {
                "AUG26": {"f_source": "parity_inferred", "f_value": 4102.0},
                "SEP26": {"f_source": "parity_inferred", "f_value": 4105.0},
            },
        },
        "gex": {
            "netgex_aggregate": {
                "net_gex": net_gex,
                "gamma_zero": {
                    "price": 4110.0,
                    "method": "linear_interpolation",
                    "scope": "aggregate_across_expiries",
                },
            },
            "by_expiry": {
                "AUG26": {
                    "summary": {"net_gex": -70.0},
                    "iv_skew": {
                        "atm_iv": 0.19,
                        "call_25d_iv": 0.18,
                        "put_25d_iv": 0.21,
                        "skew_25d": 0.03,
                    },
                },
                "SEP26": {
                    "summary": {"net_gex": -50.0},
                    "iv_skew": {
                        "atm_iv": 0.20,
                        "call_25d_iv": 0.19,
                        "put_25d_iv": 0.22,
                        "skew_25d": 0.03,
                    },
                },
            },
        },
        "support_resistance": {
            "support": [{"strike": 4050.0, "wall_score": 0.8}],
            "resistance": [{"strike": 4200.0, "wall_score": 0.9}],
        },
        "wall_scores": [
            {
                "strike": 4095.0,
                "expiry": "AUG26",
                "wall_type": "pin",
                "wall_score": 0.7,
            }
        ],
        "normalization": {"rows_missing_settlement": 0},
        "data_quality": {
            "categories": {"rows_missing_settlement": 0, "proxy_strikes": 3},
            "warnings": [],
        },
        "audit": {
            "black76_audit": {
                "AUG26": {
                    "expiry_date": "2026-08-25",
                    "expiry_source": "cme_contract_calendar",
                    "expiry_confidence": "high",
                },
                "SEP26": {
                    "expiry_date": "2026-09-25",
                    "expiry_source": "cme_contract_calendar",
                    "expiry_confidence": "confirmed",
                },
            },
            "data_audit": {"proxy_rows": 3, "proxy_gex_share": 0.01},
            "gex_audit": {
                "net_gex": net_gex,
                "proxy_included_in_zero": False,
            },
        },
    }


def test_builds_immutable_deterministic_formal_snapshot() -> None:
    payload = _options_output()
    before = copy.deepcopy(payload)

    first = adapt_options_analysis_to_cme_options_regime(payload, source_snapshot_id=FEATURE_ID, as_of=AS_OF)
    second = build_cme_options_regime_snapshot(payload, source_snapshot_id=FEATURE_ID, as_of=AS_OF)

    assert first == second
    assert payload == before
    assert isinstance(first, CMEOptionsRegimeSnapshot)
    assert first.snapshot_id == f"cme_options_regime.v1:{first.payload_hash}"
    assert first.source_snapshot_id == FEATURE_ID
    assert first.options_snapshot_id == "options:2026-07-29:og-test"
    assert first.underlying_price == 4100.0
    assert first.net_gex == -120.0
    assert first.gamma_flip == 4110.0
    assert first.pin is not None and first.pin.strike == 4095.0
    assert first.call_wall is not None and first.call_wall.strike == 4200.0
    assert first.put_wall is not None and first.put_wall.strike == 4050.0
    assert [(item.expiry, item.dte) for item in first.expiry_scope] == [
        ("AUG26", 27),
        ("SEP26", 58),
    ]
    assert len(first.skew) == 2
    assert first.regime is CMEOptionsRegime.PINNING
    assert first.directional_bias == "neutral"
    assert first.settlement_status == "FINAL"
    assert (first.freshness_status, first.quality_status, first.alignment_status) == (
        "fresh",
        "accepted",
        "aligned",
    )
    assert {item.name for item in first.input_snapshot_ids} == {
        "parsed_cme",
        "options_output",
    }
    assert first.model_disclosure.proxy_included_in_gamma_flip is False
    with pytest.raises(ValidationError):
        first.underlying_price = 1.0


def test_net_gex_sign_alone_never_creates_direction() -> None:
    payload = _options_output(net_gex=-999_999.0)
    payload["gex"]["by_expiry"]["AUG26"]["summary"]["net_gex"] = -500_000.0
    payload["gex"]["by_expiry"]["SEP26"]["summary"]["net_gex"] = -499_999.0
    payload.pop("support_resistance")
    payload["wall_scores"] = []
    payload["gex"]["by_expiry"]["AUG26"].pop("iv_skew")
    payload["gex"]["by_expiry"]["SEP26"].pop("iv_skew")

    result = build_cme_options_regime_snapshot(payload, source_snapshot_id=FEATURE_ID, as_of=AS_OF)

    assert result.directional_bias == "unavailable"
    assert result.regime is CMEOptionsRegime.UNAVAILABLE
    assert result.quality_status == "blocked"
    assert "TWO_SIDED_WALL_STRUCTURE_MISSING" in result.reason_codes
    assert "STRUCTURED_SKEW_MISSING" in result.reason_codes


def test_explicit_typed_direction_can_be_carried_without_adapter_inference() -> None:
    neutral = build_cme_options_regime_snapshot(
        _options_output(),
        source_snapshot_id=FEATURE_ID,
        as_of=AS_OF,
    )
    explicit = CMEOptionsRegimeSnapshotInput.model_validate(
        {
            **neutral.model_dump(exclude={"payload_hash", "snapshot_id"}),
            "regime": "normal",
            "directional_bias": "bullish",
            "reason_codes": ("EXPLICIT_TYPED_DIRECTIONAL_EVIDENCE",),
        }
    )

    result = build_cme_options_regime_snapshot(explicit)

    assert result.quality_status == "accepted"
    assert result.regime is CMEOptionsRegime.NORMAL
    assert result.directional_bias == "bullish"


@pytest.mark.parametrize("status", ["PRELIM", "PRELIM_assumed", "UNKNOWN"])
def test_non_final_settlement_withholds_direction(status: str) -> None:
    result = build_cme_options_regime_snapshot(
        _options_output(status=status), source_snapshot_id=FEATURE_ID, as_of=AS_OF
    )

    assert result.settlement_status != "FINAL"
    assert result.quality_status == "observe"
    assert result.directional_bias == "unavailable"
    assert "FINAL_SETTLEMENT_REQUIRED_FOR_DIRECTION" in result.reason_codes


def test_missing_lineage_fails_closed() -> None:
    payload = _options_output()
    payload.pop("snapshot_id")
    payload["data_source"].pop("input_snapshot_ids")

    result = build_cme_options_regime_snapshot(payload, source_snapshot_id=FEATURE_ID, as_of=AS_OF)

    assert result.input_snapshot_ids == ()
    assert result.quality_status == "blocked"
    assert result.directional_bias == "unavailable"
    assert "CME_INPUT_LINEAGE_MISSING" in result.reason_codes


def test_future_or_unaware_timestamps_are_not_accepted() -> None:
    payload = _options_output()
    payload["generated_at"] = "2026-07-29T22:00:00Z"
    payload["parameters"]["report_p0_timestamp"] = "2026-07-29T22:00:00Z"

    result = build_cme_options_regime_snapshot(payload, source_snapshot_id=FEATURE_ID, as_of=AS_OF)

    assert result.generated_at is None
    assert result.underlying_as_of is None
    assert result.source_refs == ()
    assert result.alignment_status == "misaligned"
    assert result.quality_status == "blocked"
    assert result.directional_bias == "unavailable"


def test_estimated_expiry_is_observe_only_and_keeps_dte_disclosure() -> None:
    payload = _options_output()
    for value in payload["audit"]["black76_audit"].values():
        value.update(
            expiry_source="estimated_from_delivery_month",
            expiry_confidence="medium",
        )

    result = build_cme_options_regime_snapshot(payload, source_snapshot_id=FEATURE_ID, as_of=AS_OF)

    assert result.expiry_scope[0].dte == 27
    assert result.alignment_status == "unknown"
    assert result.quality_status == "observe"
    assert result.directional_bias == "unavailable"
    assert "EXPIRY_ALIGNMENT_UNVERIFIED" in result.reason_codes


def test_identity_tampering_is_rejected() -> None:
    result = build_cme_options_regime_snapshot(_options_output(), source_snapshot_id=FEATURE_ID, as_of=AS_OF)
    payload = result.model_dump()
    payload["net_gex"] = 42.0

    with pytest.raises(ValidationError, match="identity"):
        CMEOptionsRegimeSnapshot.model_validate(payload)


def test_output_scope_and_skew_expiry_mismatch_fail_closed() -> None:
    payload = _options_output()
    payload["data_source"]["product"] = "GC"
    payload["gex"]["by_expiry"].pop("SEP26")

    result = build_cme_options_regime_snapshot(payload, source_snapshot_id=FEATURE_ID, as_of=AS_OF)

    assert result.alignment_status == "misaligned"
    assert result.quality_status == "blocked"
    assert result.directional_bias == "unavailable"
    assert "CME_OUTPUT_SCOPE_INVALID" in result.reason_codes
    assert "SKEW_EXPIRY_SCOPE_MISMATCH" in result.reason_codes


def test_quality_warnings_prevent_accepted_direction() -> None:
    payload = _options_output()
    payload["data_quality"]["warnings"] = ["grid_skipped_rows_without_iv"]

    result = build_cme_options_regime_snapshot(payload, source_snapshot_id=FEATURE_ID, as_of=AS_OF)

    assert result.quality_status == "observe"
    assert result.directional_bias == "unavailable"
    assert "OPTIONS_QUALITY_DEGRADED" in result.reason_codes


def test_adapter_requires_feature_snapshot_identity_and_aware_as_of() -> None:
    with pytest.raises(ValidationError):
        build_cme_options_regime_snapshot(_options_output(), source_snapshot_id="analysis-snapshot", as_of=AS_OF)
    with pytest.raises(ValueError, match="timezone-aware"):
        build_cme_options_regime_snapshot(
            _options_output(),
            source_snapshot_id=FEATURE_ID,
            as_of=datetime(2026, 7, 29, 21, 0),
        )
