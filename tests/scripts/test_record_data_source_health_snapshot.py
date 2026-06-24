from __future__ import annotations

import json


def test_record_source_health_snapshot_dry_run_does_not_persist(monkeypatch, capsys) -> None:
    from scripts import record_data_source_health_snapshot as script

    persisted = False

    def fail_record(*, session_factory, snapshot_date=None):
        nonlocal persisted
        persisted = True
        raise AssertionError("dry run must not persist")

    monkeypatch.setattr(script, "record_daily_source_health_snapshot", fail_record)
    monkeypatch.setattr(
        script,
        "get_data_source_health_latest",
        lambda date=None: {
            "snapshot_date": date,
            "overall_status": "LIVE",
            "counts": {"total": 1, "live": 1, "partial": 0, "unavailable": 0, "stale": 0},
            "items": [{"source_key": "fred"}],
        },
    )

    rc = script.main(["--date", "2026-06-24", "--dry-run"])

    assert rc == 0
    assert persisted is False
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["snapshot_date"] == "2026-06-24"
    assert output["planned_items"] == 1


def test_record_source_health_snapshot_persists_with_database_url(monkeypatch, capsys) -> None:
    from scripts import record_data_source_health_snapshot as script

    calls: list[dict] = []

    def fake_session_factory(database_url: str):
        calls.append({"database_url": database_url})
        return object

    def fake_record(*, session_factory, snapshot_date=None):
        calls.append({"snapshot_date": snapshot_date, "session_factory": session_factory})
        return {
            "snapshot_date": snapshot_date,
            "overall_status": "PARTIAL",
            "counts": {"total": 2, "live": 1, "partial": 1, "unavailable": 0, "stale": 1},
            "items": [{"source_key": "fred"}, {"source_key": "jin10_mcp_flash"}],
        }

    monkeypatch.setattr(script, "_session_factory", fake_session_factory)
    monkeypatch.setattr(script, "record_daily_source_health_snapshot", fake_record)

    rc = script.main(["--date", "2026-06-24", "--database-url", "sqlite:////tmp/source-health-test.db"])

    assert rc == 0
    assert calls[0] == {"database_url": "sqlite:////tmp/source-health-test.db"}
    assert calls[1]["snapshot_date"] == "2026-06-24"
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is False
    assert output["persisted_items"] == 2
    assert output["overall_status"] == "PARTIAL"
