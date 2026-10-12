from types import SimpleNamespace

from scripts import run_gold_daily_report as report
from tests.analysis.test_gold_strategy_policy import _snapshot
from tests.runtime.test_premarket_snapshot_authority import _factory, _stage_success


def test_explicit_input_dry_run_requires_db(tmp_path):
    result = report.run_gold_daily_report(
        trade_date="2026-09-29", storage_root=tmp_path, dry_run=True, premarket_run_id="a",
    )
    assert result["reason"] == "selected_premarket_requires_database"
    assert not list(tmp_path.iterdir())


def test_cli_explicit_dry_run_opens_readonly_transaction(monkeypatch, capsys):
    calls = []
    session = SimpleNamespace(
        rollback=lambda: calls.append("rollback"),
        commit=lambda: calls.append("commit"),
        close=lambda: calls.append("close"),
    )

    def run(**kwargs):
        assert kwargs["db"] is session
        assert kwargs["premarket_run_id"] == "selected-input"
        assert kwargs["dry_run"] is True
        return {"status": "dry_run"}

    monkeypatch.setattr(report, "run_gold_daily_report", run)
    assert report.main(
        ["--date", "2026-09-29", "--premarket-run-id", "selected-input", "--dry-run"],
        session_factory=lambda: session,
    ) == 0
    assert calls == ["rollback", "close"]
    assert '"dry_run"' in capsys.readouterr().out


def test_explicit_dry_run_binds_registered_snapshot_and_rejects_tampering(tmp_path, monkeypatch):
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    monkeypatch.setattr(report, "prepare_gold_policy_current_feature", lambda **_: current)
    root = tmp_path / "storage"
    with _factory(tmp_path)() as db:
        selected, _, path = _stage_success(db, root, trade_date="2025-01-21")
        _stage_success(db, root, trade_date="2025-01-21")
        kwargs = dict(trade_date="2025-01-21", storage_root=root, db=db,
                      dry_run=True, premarket_run_id=str(selected.id))
        result = report.run_gold_daily_report(**kwargs)
        assert result["status"] == "dry_run"
        assert result["input_authority"]["run_id"] == str(selected.id)
        assert result["snapshot_path"] == str(path)
        path.write_text('{}')
        result = report.run_gold_daily_report(**kwargs)
        assert result["status"] == "blocked"
        assert result["reason"] == "authority_integrity_invalid"
        assert not (root / "analysis").exists()
