"""Fixture-backed HTTP acceptance for the Gold result identity contract.

The report fixture is produced, verified, and registered by the existing
delivery fixture.  This file only isolates service storage reads and supplies
empty market/options inputs for the live endpoint; it does not mock the Gold
runtime, bundle verifier, or report registry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.api.test_gold_policy_report_delivery_api import (
    _client_with_session,
    _gold_policy_delivery_env as shared_gold_policy_delivery_env,  # noqa: F401
)


_SUBJECT_FIELDS = {
    "kind",
    "run_id",
    "premarket_snapshot_id",
    "feature_snapshot_id",
    "result_id",
    "state_id",
    "strategy_id",
    "receipt_id",
    "bundle_ref",
    "verification_status",
    "reason_code",
}
_EFFECTIVE_BASELINE_FIELDS = _SUBJECT_FIELDS | {
    "status",
    "held",
    "authority_ready",
    "quality_status",
    "strategy_status",
    "decision_as_of",
}
_RELATIONSHIP_STATUSES = {
    "same_effective_head",
    "different_result",
    "unverified",
    "unavailable",
}


@pytest.fixture
def _identity_delivery_env(shared_gold_policy_delivery_env, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    """Use the real report fixture while keeping all read-side storage local."""

    from apps.api.services import gold_mainline_service, live_strategy_service, report_service

    root: Path = shared_gold_policy_delivery_env["tmp_path"]
    monkeypatch.setattr(gold_mainline_service, "_PROJECT_ROOT", root)
    monkeypatch.setattr(live_strategy_service, "_PROJECT_ROOT", root)
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", root)
    monkeypatch.setattr(live_strategy_service, "get_strategy_card_read_model_latest", lambda **_: None)
    monkeypatch.setattr(
        live_strategy_service,
        "get_market_candles",
        lambda **_: {"status": "unavailable", "candles": []},
    )
    monkeypatch.setattr(live_strategy_service, "get_options_decision", lambda **_: {})
    return shared_gold_policy_delivery_env


def _assert_string_or_none(value: Any) -> None:
    assert value is None or isinstance(value, str)


def _assert_result_identity(identity: Any) -> dict[str, Any]:
    assert isinstance(identity, dict)
    assert identity["schema_version"] == "gold_result_identity.v1"

    subject = identity["subject"]
    assert isinstance(subject, dict)
    assert _SUBJECT_FIELDS <= subject.keys()
    assert isinstance(subject["kind"], str)
    for key in _SUBJECT_FIELDS - {"kind"}:
        _assert_string_or_none(subject[key])

    effective_baseline = identity.get("effective_baseline")
    if effective_baseline is not None:
        assert isinstance(effective_baseline, dict)
        assert _EFFECTIVE_BASELINE_FIELDS <= effective_baseline.keys()
        assert isinstance(effective_baseline["kind"], str)
        for key in _EFFECTIVE_BASELINE_FIELDS - {"kind", "held", "authority_ready", "status"}:
            _assert_string_or_none(effective_baseline[key])
        assert isinstance(effective_baseline["status"], str)
        assert isinstance(effective_baseline["held"], bool)
        assert isinstance(effective_baseline["authority_ready"], bool)

    relationship = identity["relationship"]
    assert isinstance(relationship, dict)
    assert relationship["status"] in _RELATIONSHIP_STATUSES
    _assert_string_or_none(relationship["reason_code"])
    return identity


def _fetch_three_views(env: dict[str, Any]) -> dict[str, dict[str, Any]]:
    from apps.api.main import app

    factory = env["factory"]
    report_id = env["report_id"]
    with factory() as db:
        client = _client_with_session(db)
        try:
            responses = {
                "report": client.get(f"/api/reports/{report_id}"),
                "mainlines": client.get("/api/gold/mainlines/latest"),
                "live": client.get("/api/live-strategy/latest", params={"asset": "XAUUSD"}),
            }
        finally:
            app.dependency_overrides.clear()

    for name, response in responses.items():
        assert response.status_code == 200, f"{name}: {response.status_code} {response.text[:500]}"
    return {name: response.json() for name, response in responses.items()}


def test_existing_gold_views_deliver_result_identity_and_gate_prebootstrap_direction(
    _identity_delivery_env,
) -> None:
    env = _identity_delivery_env
    views = _fetch_three_views(env)

    identities = {
        name: _assert_result_identity(payload["result_identity"])
        for name, payload in views.items()
    }

    report_identity = identities["report"]
    assert report_identity["subject"]["verification_status"] == "verified"
    assert views["report"]["data_status"] == "partial"

    live = views["live"]
    live_baseline = live["data_quality"]["gold_baseline"]
    assert live_baseline["authority_ready"] is False
    assert live_baseline["direction"] == "none"
    assert live["active_scenario"] is None
    assert live["strategy_status"] == "SUSPENDED_DATA"


def test_tampered_report_is_unverified_without_changing_report_index(
    _identity_delivery_env,
) -> None:
    env = _identity_delivery_env
    factory = env["factory"]
    report_id = env["report_id"]
    bundle_path: Path = env["bundle_path"]
    target = bundle_path / "analysis.md"
    original = target.read_text(encoding="utf-8")

    from database.models.report import ReportItem

    with factory() as db:
        before_count = db.query(ReportItem).count()

    target.write_text(original + "\nTampered by result identity acceptance test.\n", encoding="utf-8")
    try:
        from apps.api.main import app

        with factory() as db:
            client = _client_with_session(db)
            try:
                response = client.get(f"/api/reports/{report_id}")
            finally:
                app.dependency_overrides.clear()
        assert response.status_code == 200, response.text[:500]
        payload = response.json()
        identity = _assert_result_identity(payload["result_identity"])
        assert identity["subject"]["verification_status"] != "verified"
    finally:
        target.write_text(original, encoding="utf-8")

    with factory() as db:
        after_count = db.query(ReportItem).count()
    assert after_count == before_count


def test_legacy_gold_mainlines_with_same_run_are_not_same_effective_head(
    _identity_delivery_env,
) -> None:
    env = _identity_delivery_env
    root: Path = env["tmp_path"]
    date = env["trade_date"]
    run_id = env["run_id"]
    mainlines_path = root / "storage" / "features" / "news" / date / run_id / "gold_event_mainlines.json"
    overview_path = root / "storage" / "analysis" / "gold_mainlines" / date / run_id / "gold_macro_overview.json"
    mainlines_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    mainlines_path.write_text(
        json.dumps(
            {
                "schema_version": "gold-event-mainlines-v1",
                "asset": "XAUUSD",
                "as_of": f"{date}T12:00:00+00:00",
                "status": "partial",
                "mainlines": [],
                "event_links": [],
                "dominant_forces": [],
                "source_refs": [{"source": "legacy_fixture", "source_ref": "legacy:mainlines"}],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    overview_path.write_text(
        json.dumps(
            {
                "schema_version": "gold-macro-overview-v1",
                "retrieved_date": date,
                "run_id": run_id,
                "input_snapshot_ids": {
                    "gold_event_mainlines": f"features/news/{date}/{run_id}/gold_event_mainlines.json",
                },
                "status": "partial",
                "asset": "XAUUSD",
                "as_of": f"{date}T12:00:00+00:00",
                "theme_rankings": [],
                "source_refs": [{"source": "legacy_fixture", "source_ref": "legacy:mainlines"}],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    views = _fetch_three_views(env)
    report_identity = _assert_result_identity(views["report"]["result_identity"])
    mainline_identity = _assert_result_identity(views["mainlines"]["result_identity"])
    assert views["mainlines"]["run_id"] == run_id
    assert report_identity["subject"]["run_id"] == run_id
    assert mainline_identity["relationship"]["status"] != "same_effective_head"
    assert views["report"]["gold_macro_overview"] is None
