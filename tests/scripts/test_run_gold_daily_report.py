from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.daily_close_store import (
    load_gold_daily_close_head,
    verify_gold_daily_close_bundle,
)
from apps.runtime.premarket_snapshot_authority import PremarketSnapshotAuthority
from scripts import run_gold_daily_report as report
from tests.analysis.test_gold_strategy_policy import _snapshot
from tests.analysis.test_gold_cme_options_regime import _options_output


def _write_snapshot(root: Path, trade_date: str) -> Path:
    path = root / "features" / "snapshots" / "XAUUSD" / trade_date / "premarket" / "premarket_snapshot.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"trade_date": trade_date, "legacy_context": "ignored"}), encoding="utf-8")
    return path


def _current_input(current):
    """Return only the current contract used by the formal script seam."""

    return current


def _storage_bytes(root: Path) -> dict[str, tuple[str, bytes | str]]:
    """Capture entries without following links, including empty directories."""

    return {
        str(path.relative_to(root)): (
            ("symlink", str(path.readlink()))
            if path.is_symlink()
            else ("file", path.read_bytes()) if path.is_file() else ("directory", "")
        )
        for path in root.rglob("*")
    }


def _forbid_report_mutation(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("rejected target or dry-run must not execute or register a report")

    monkeypatch.setattr(report, "execute_gold_daily_close_runtime", forbidden)
    monkeypatch.setattr(report, "register_gold_policy_report_bundle", forbidden)


def test_no_jin10_entrypoint_writes_complete_hold_package_idempotently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: _current_input(current),
    )

    first = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )
    before = _storage_bytes(tmp_path)
    second = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )

    assert first["status"] == "completed"
    assert first["jin10"] == "not_used"
    assert first["canonical_action"] == "hold"
    assert first["report_status"] == "degraded"
    assert len(first["report_paths"]) == 9
    assert all(Path(path).is_file() for path in first["report_paths"])
    assert second == first
    assert _storage_bytes(tmp_path) == before
    _forbid_report_mutation(monkeypatch)
    preview = report.run_gold_daily_report(
        trade_date="2025-01-21", storage_root=tmp_path, dry_run=True, db=object(),
    )
    assert preview["status"] == "dry_run"
    assert "registry_status" not in preview
    assert _storage_bytes(tmp_path) == before
    assert "apps.analysis.jin10" not in Path(report.__file__).read_text(encoding="utf-8")


def test_same_day_formal_options_are_rendered_without_releasing_directional_trigger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    options_payload = json.loads(json.dumps(_options_output()).replace("2026-07-29", "2025-01-21"))
    options_path = tmp_path / "features/cme/2025-01-21/formal-options/options_analysis.json"
    options_path.parent.mkdir(parents=True)
    options_path.write_text(json.dumps(options_payload), encoding="utf-8")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: _current_input(current),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )

    assert result["status"] == "completed"
    assert result["report_status"] == "degraded"
    analysis = next(
        Path(path).read_text(encoding="utf-8") for path in result["report_paths"] if path.endswith("analysis.md")
    )
    structured = json.loads(
        next(
            Path(path).read_text(encoding="utf-8")
            for path in result["report_paths"]
            if path.endswith("report_structured.json")
        )
    )
    data_quality = json.loads(
        next(
            Path(path).read_text(encoding="utf-8")
            for path in result["report_paths"]
            if path.endswith("data_quality.json")
        )
    )
    strategy = json.loads(Path(result["strategy_card_paths"][0]).read_text(encoding="utf-8"))
    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=Path(result["report_paths"][0]).parent,
    )
    assert "## 策略与原因" in analysis
    assert "CME GC Gamma Flip 参考：4110.0" in analysis
    assert "触发位：unavailable" in analysis
    assert any(fact["fact_id"] == "options.net_gex" for section in structured["sections"] for fact in section["facts"])
    assert verification.status == "valid"
    assert data_quality["domain_status"]["options"] == "observe"
    assert "OPTIONS_CONFIRMATION" in data_quality["prohibited_outputs"]
    assert "TRIGGERED_STRATEGY" in data_quality["prohibited_outputs"]
    assert strategy["status"] not in {
        "LONG_RESEARCH_TRIGGERED",
        "SHORT_RESEARCH_TRIGGERED",
    }


@pytest.mark.parametrize("dry_run", [True, False])
def test_existing_tampered_report_never_returns_completed(
    tmp_path: Path,
    monkeypatch,
    dry_run: bool,
) -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: _current_input(current),
    )

    first = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )
    analysis_path = next(Path(path) for path in first["report_paths"] if path.endswith("analysis.md"))
    analysis_path.write_text(
        analysis_path.read_text(encoding="utf-8") + "\nTAMPERED\n",
        encoding="utf-8",
    )
    before = _storage_bytes(tmp_path)
    _forbid_report_mutation(monkeypatch)

    second = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        dry_run=dry_run,
    )

    assert first["status"] == "completed"
    assert second["status"] == "blocked"
    assert second["reason"] == "existing_bundle_invalid"
    assert _storage_bytes(tmp_path) == before
    assert "TAMPERED" in analysis_path.read_text(encoding="utf-8")


def test_no_jin10_entrypoint_publishes_degraded_no_trade_for_blocked_feature(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    _write_snapshot(tmp_path, "2025-01-22")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: _current_input(current),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-22",
        storage_root=tmp_path,
    )

    assert result["status"] == "completed"
    assert result["canonical_action"] == "hold"
    assert result["report_status"] == "degraded"
    strategy = json.loads(Path(result["strategy_card_paths"][0]).read_text(encoding="utf-8"))
    assert strategy["status"] == "NO_TRADE"


def test_dry_run_validates_formal_inputs_without_writing(tmp_path: Path, monkeypatch) -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: _current_input(current),
    )
    before = _storage_bytes(tmp_path)
    _forbid_report_mutation(monkeypatch)

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["jin10"] == "not_used"
    assert not (tmp_path / "analysis").exists()
    assert _storage_bytes(tmp_path) == before


def test_confirmatory_gaps_publish_observe_package(tmp_path: Path, monkeypatch) -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "gold_policy" / "readiness_v2"
    ready = json.loads((fixture_dir / "ready.json").read_text(encoding="utf-8"))["input"]
    case = json.loads((fixture_dir / "confirmatory_missing.json").read_text(encoding="utf-8"))
    current_payload = json.loads(json.dumps(ready))
    for name, updates in case["patch"].items():
        current_payload[name].update(updates)
    previous_payload = json.loads(json.dumps(ready).replace("2025-01-17", "2025-01-16"))
    previous = build_feature_snapshot(previous_payload)
    current = build_feature_snapshot(current_payload)
    _write_snapshot(tmp_path, "2025-01-16")
    _write_snapshot(tmp_path, "2025-01-17")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: (
            _current_input(previous)
            if kwargs["snapshot"]["trade_date"] == "2025-01-16"
            else _current_input(current)
        ),
    )

    bootstrap = report.run_gold_daily_report(
        trade_date="2025-01-16",
        storage_root=tmp_path,
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-17",
        storage_root=tmp_path,
    )

    assert bootstrap["status"] == "completed"
    assert result["status"] == "completed"
    assert result["report_status"] == "observe"


def test_newer_same_session_snapshot_creates_linked_revision(tmp_path: Path, monkeypatch) -> None:
    first_feature = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    revised_payload = first_feature.model_dump(
        mode="json",
        exclude={"data_quality", "payload_hash", "snapshot_id"},
    )
    revised_as_of = first_feature.as_of + timedelta(hours=1)
    revised_payload["as_of"] = revised_as_of.isoformat()
    revised_payload["xauusd_spot"]["value"] += 1.0
    revised_payload["xauusd_spot"]["as_of"] = revised_as_of.isoformat()
    revised_feature = build_feature_snapshot(revised_payload)
    _write_snapshot(tmp_path, "2025-01-21")
    current = first_feature
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: _current_input(current),
    )

    first = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )
    current = revised_feature
    second = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )

    assert first["status"] == second["status"] == "completed"
    assert first["run_id"] != second["run_id"]
    latest = load_gold_daily_close_head(storage_root=tmp_path)
    assert latest.latest_receipt is not None
    assert latest.latest_receipt.revision_no == 2
    assert latest.latest_receipt.supersedes_receipt_id


@pytest.mark.parametrize("dry_run", [True, False])
def test_explicit_run_id_does_not_reuse_a_bundle_for_a_different_feature(
    tmp_path: Path,
    monkeypatch,
    dry_run: bool,
) -> None:
    first_feature = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    revised_payload = first_feature.model_dump(
        mode="json",
        exclude={"data_quality", "payload_hash", "snapshot_id"},
    )
    revised_as_of = first_feature.as_of + timedelta(hours=1)
    revised_payload["as_of"] = revised_as_of.isoformat()
    revised_payload["xauusd_spot"]["value"] += 1.0
    revised_payload["xauusd_spot"]["as_of"] = revised_as_of.isoformat()
    revised_feature = build_feature_snapshot(revised_payload)
    _write_snapshot(tmp_path, "2025-01-21")
    current = first_feature
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: _current_input(current),
    )

    first = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        run_id="operator-selected-run",
    )
    current = revised_feature
    before = _storage_bytes(tmp_path)
    _forbid_report_mutation(monkeypatch)
    second = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        run_id="operator-selected-run",
        dry_run=dry_run,
    )

    assert first["status"] == "completed"
    assert second == {
        "status": "blocked",
        "reason": "existing_bundle_feature_snapshot_mismatch",
        "trade_date": "2025-01-21",
        "run_id": "operator-selected-run",
        "snapshot_path": str(
            tmp_path
            / "features"
            / "snapshots"
            / "XAUUSD"
            / "2025-01-21"
            / "premarket"
            / "premarket_snapshot.json"
        ),
        "jin10": "not_used",
    }
    assert _storage_bytes(tmp_path) == before


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize(
    "target_kind",
    ["empty", "incomplete", "file", "symlink", "dangling_symlink", "parent_symlink", "dangling_parent_symlink"],
)
def test_invalid_existing_target_is_never_repaired(
    tmp_path: Path, monkeypatch, dry_run: bool, target_kind: str,
) -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setattr(report, "prepare_gold_policy_current_feature", lambda **kwargs: current)
    bundle = tmp_path / "analysis/gold_mainlines/2025-01-21/protected-run/daily_close"
    bundle.parent.mkdir(parents=True)
    if target_kind in {"empty", "incomplete"}:
        bundle.mkdir()
        if target_kind == "incomplete":
            (bundle / "sentinel").write_bytes(b"preserve incomplete history")
    elif target_kind == "file":
        bundle.write_bytes(b"preserve ordinary file")
    else:
        referent = tmp_path / "referent"
        if "dangling" not in target_kind:
            referent.mkdir()
            (referent / "sentinel").write_bytes(b"preserve symlink destination")
        if "parent" in target_kind:
            bundle.parent.rmdir()
            bundle.parent.symlink_to(referent, target_is_directory=True)
        else:
            bundle.symlink_to(referent, target_is_directory=True)
    before = _storage_bytes(tmp_path)
    _forbid_report_mutation(monkeypatch)

    result = report.run_gold_daily_report(
        trade_date="2025-01-21", storage_root=tmp_path, run_id="protected-run", dry_run=dry_run,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "existing_bundle_invalid"
    assert _storage_bytes(tmp_path) == before


@pytest.mark.parametrize("mode", ["offline_dry_run", "selected_dry_run", "write"])
@pytest.mark.parametrize("failure", ["identity", "tampered", "incomplete", "artifact_symlink"])
def test_cli_rejects_existing_history_without_commit_or_registration(
    tmp_path: Path, monkeypatch, capsys, mode: str, failure: str,
) -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    snapshot_path = _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setattr(report, "prepare_gold_policy_current_feature", lambda **kwargs: current)
    args = ["--date", "2025-01-21", "--storage-root", str(tmp_path), "--run-id", "cli-history"]
    bundle = tmp_path / "analysis/gold_mainlines/2025-01-21/cli-history/daily_close"
    if failure == "incomplete":
        bundle.mkdir(parents=True)
        (bundle / "sentinel").write_bytes(b"incomplete history")
    else:
        first = report.run_gold_daily_report(
            trade_date="2025-01-21", storage_root=tmp_path, run_id="cli-history",
        )
        assert first["status"] == "completed"
        assert verify_gold_daily_close_bundle(storage_root=tmp_path, bundle_path=bundle).status == "valid"
        if failure == "identity":
            payload = current.model_dump(mode="json", exclude={"data_quality", "payload_hash", "snapshot_id"})
            payload["xauusd_spot"]["value"] += 1.0
            current = build_feature_snapshot(payload)
        elif failure == "tampered":
            (bundle / "analysis.md").write_bytes(b"tampered history")
        else:
            artifact = bundle / "analysis.md"
            referent = tmp_path / "original-analysis.md"
            referent.write_bytes(artifact.read_bytes())
            artifact.unlink()
            artifact.symlink_to(referent)
    before = _storage_bytes(tmp_path)
    _forbid_report_mutation(monkeypatch)
    calls = []
    session = SimpleNamespace(
        commit=lambda: pytest.fail("blocked preflight must not commit"),
        rollback=lambda: calls.append("rollback"),
        close=lambda: calls.append("close"),
    )

    def factory():
        assert mode != "offline_dry_run", "offline dry-run must not open a database session"
        calls.append("session")
        return session

    def authority(db, **kwargs):
        assert db is session
        assert kwargs.get("premarket_run_id") == ("selected-input" if mode == "selected_dry_run" else None)
        calls.append("authority")
        return PremarketSnapshotAuthority(
            status="found", reason_code="authoritative_gold_daily_report_premarket_snapshot_found",
            snapshot_path=snapshot_path, run_id="selected-input", snapshot_id="selected-snapshot",
            file_sha256=hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        )

    monkeypatch.setattr(report, "resolve_gold_daily_report_premarket_snapshot", authority)
    if mode != "write":
        args.append("--dry-run")
    if mode == "selected_dry_run":
        args.extend(["--premarket-run-id", "selected-input"])

    exit_code = report.main(args, session_factory=factory)
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert result["status"] == "blocked"
    assert result["reason"] == (
        "existing_bundle_feature_snapshot_mismatch" if failure == "identity" else "existing_bundle_invalid"
    )
    assert calls == ([] if mode == "offline_dry_run" else ["session", "authority", "rollback", "close"])
    assert _storage_bytes(tmp_path) == before


@pytest.mark.parametrize("existing", [True, False])
def test_selected_cli_dry_run_never_writes_registers_or_commits(
    tmp_path: Path, monkeypatch, capsys, existing: bool,
) -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    snapshot_path = _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setattr(report, "prepare_gold_policy_current_feature", lambda **kwargs: current)
    if existing:
        first = report.run_gold_daily_report(
            trade_date="2025-01-21", storage_root=tmp_path, run_id="selected-preview",
        )
        assert first["status"] == "completed"
    authority = PremarketSnapshotAuthority(
        status="found", reason_code="authoritative_gold_daily_report_premarket_snapshot_found",
        snapshot_path=snapshot_path, run_id="selected-input", snapshot_id="selected-snapshot",
        file_sha256=hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
    )
    calls = []
    session = SimpleNamespace(
        commit=lambda: pytest.fail("dry-run must not commit"),
        rollback=lambda: calls.append("rollback"),
        close=lambda: calls.append("close"),
    )

    def resolve(db, **kwargs):
        assert db is session
        assert kwargs["premarket_run_id"] == "selected-input"
        calls.append("authority")
        return authority

    monkeypatch.setattr(report, "resolve_gold_daily_report_premarket_snapshot", resolve)
    _forbid_report_mutation(monkeypatch)
    before = _storage_bytes(tmp_path)

    exit_code = report.main(
        ["--date", "2025-01-21", "--storage-root", str(tmp_path), "--run-id", "selected-preview",
         "--premarket-run-id", "selected-input", "--dry-run"],
        session_factory=lambda: session,
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["status"] == "dry_run"
    assert result["input_authority"] == {
        "status": "found", "run_id": "selected-input", "snapshot_id": "selected-snapshot",
    }
    assert "registry_status" not in result
    assert calls == ["authority", "rollback", "close"]
    assert _storage_bytes(tmp_path) == before


def test_snapshot_and_run_id_fail_closed(tmp_path: Path) -> None:
    missing = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )
    outside = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        snapshot_path=tmp_path.parent / "outside.json",
    )

    assert missing["reason"] == "premarket_snapshot_missing"
    assert outside["reason"] == "snapshot_path_outside_storage_root"


def test_formal_report_does_not_use_generic_previous_lookup(tmp_path: Path, monkeypatch) -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    snapshot_path = _write_snapshot(tmp_path, "2025-01-21")

    def fail_lookup(**kwargs):
        pytest.fail("formal report must not resolve a generic filesystem predecessor")

    from apps.analysis.gold_policy import runtime_inputs

    monkeypatch.setattr(runtime_inputs, "load_previous_feature_snapshot", fail_lookup)
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: current,
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["snapshot_path"] == str(snapshot_path)
    assert result["feature_snapshot_id"] == current.snapshot_id
    assert result["predecessor_status"] == "missing"
    assert not (tmp_path / "analysis").exists()


@pytest.mark.parametrize(
    ("status", "reason_code"),
    [
        ("ambiguous", "head_ambiguous"),
        ("invalid", "head_invalid"),
    ],
)
def test_formal_report_blocks_invalid_or_ambiguous_canonical_predecessor(
    tmp_path: Path,
    monkeypatch,
    status: str,
    reason_code: str,
) -> None:
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setattr(report, "prepare_gold_policy_current_feature", lambda **kwargs: current)
    monkeypatch.setattr(
        report,
        "resolve_canonical_predecessor",
        lambda **kwargs: SimpleNamespace(status=status, reason_code=reason_code, head=None),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        dry_run=True,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "gold_policy_runtime_prepare_failed"
    assert f"canonical_predecessor_{reason_code}" in result["detail"]
    assert not (tmp_path / "analysis").exists()


def test_write_path_requires_the_authority_verified_file_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    authoritative_path = (
        tmp_path
        / "features"
        / "snapshots"
        / "XAUUSD"
        / "2025-01-21"
        / "authoritative-run"
        / "premarket_snapshot.json"
    )
    authoritative_path.parent.mkdir(parents=True)
    authoritative_path.write_text(json.dumps({"trade_date": "2025-01-21"}), encoding="utf-8")
    monkeypatch.setattr(
        report,
        "resolve_gold_daily_report_premarket_snapshot",
        lambda *args, **kwargs: PremarketSnapshotAuthority(
            status="found",
            reason_code="authoritative_gold_daily_report_premarket_snapshot_found",
            snapshot_path=authoritative_path,
            run_id="authoritative-run",
            snapshot_id="XAUUSD:2025-01-21:authoritative-run",
        ),
    )
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: pytest.fail("hashless authority must not prepare a report"),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        db=object(),
    )

    assert result == {
        "status": "blocked",
        "reason": "authority_integrity_invalid",
        "trade_date": "2025-01-21",
        "authority": {
            "status": "found",
            "run_id": "authoritative-run",
            "snapshot_id": "XAUUSD:2025-01-21:authoritative-run",
        },
        "jin10": "not_used",
    }


def test_write_path_blocks_snapshot_changed_after_authority_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    authoritative_path = (
        tmp_path
        / "features"
        / "snapshots"
        / "XAUUSD"
        / "2025-01-21"
        / "authoritative-run"
        / "premarket_snapshot.json"
    )
    authoritative_path.parent.mkdir(parents=True)
    original_bytes = json.dumps({"trade_date": "2025-01-21"}).encode("utf-8")
    authoritative_path.write_bytes(original_bytes)
    monkeypatch.setattr(
        report,
        "resolve_gold_daily_report_premarket_snapshot",
        lambda *args, **kwargs: PremarketSnapshotAuthority(
            status="found",
            reason_code="authoritative_gold_daily_report_premarket_snapshot_found",
            snapshot_path=authoritative_path,
            run_id="authoritative-run",
            snapshot_id="XAUUSD:2025-01-21:authoritative-run",
            file_sha256=hashlib.sha256(original_bytes).hexdigest(),
        ),
    )
    authoritative_path.write_bytes(b' { "trade_date": "2025-01-21" }\n')
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: pytest.fail("changed authority snapshot must not prepare a report"),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        db=object(),
    )

    assert result == {
        "status": "blocked",
        "reason": "snapshot_authority_integrity_changed",
        "trade_date": "2025-01-21",
        "snapshot_path": str(authoritative_path),
        "authority": {
            "status": "found",
            "run_id": "authoritative-run",
            "snapshot_id": "XAUUSD:2025-01-21:authoritative-run",
        },
        "jin10": "not_used",
    }


def test_write_path_rejects_ambiguous_or_explicit_non_authoritative_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    requested_path = _write_snapshot(tmp_path, "2025-01-21")
    authoritative_path = (
        tmp_path
        / "features"
        / "snapshots"
        / "XAUUSD"
        / "2025-01-21"
        / "authoritative-run"
        / "premarket_snapshot.json"
    )
    authoritative_path.parent.mkdir(parents=True)
    authoritative_path.write_text(json.dumps({"trade_date": "2025-01-21"}), encoding="utf-8")
    monkeypatch.setattr(
        report,
        "resolve_gold_daily_report_premarket_snapshot",
        lambda *args, **kwargs: PremarketSnapshotAuthority(
            status="found",
            reason_code="authoritative_gold_daily_report_premarket_snapshot_found",
            snapshot_path=authoritative_path,
            run_id="authoritative-run",
            snapshot_id="XAUUSD:2025-01-21:authoritative-run",
            file_sha256=hashlib.sha256(authoritative_path.read_bytes()).hexdigest(),
        ),
    )
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: pytest.fail("non-authoritative path must not prepare a report"),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        snapshot_path=requested_path,
        db=object(),
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "snapshot_path_not_authoritative"
    assert result["authority"] == {
        "status": "found",
        "run_id": "authoritative-run",
        "snapshot_id": "XAUUSD:2025-01-21:authoritative-run",
    }
    assert not (tmp_path / "analysis").exists()


@pytest.mark.parametrize(
    ("authority_status", "reason_code"),
    [
        ("ambiguous", "multiple_successful_premarket_runs"),
        ("missing", "successful_premarket_run_missing"),
        ("unavailable", "authority_database_unavailable"),
    ],
)
def test_write_path_blocks_non_found_db_authority_without_filesystem_fallback(
    tmp_path: Path,
    monkeypatch,
    authority_status: str,
    reason_code: str,
) -> None:
    _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setattr(
        report,
        "resolve_gold_daily_report_premarket_snapshot",
        lambda *args, **kwargs: PremarketSnapshotAuthority(
            status=authority_status,  # type: ignore[arg-type]
            reason_code=reason_code,
        ),
    )
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_current_feature",
        lambda **kwargs: pytest.fail("non-found authority must not prepare a report"),
    )
    monkeypatch.setattr(
        report,
        "_existing_completed_result",
        lambda **kwargs: pytest.fail("authority must be checked before completed-bundle reuse"),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        db=object(),
    )

    assert result == {
        "status": "blocked",
        "reason": reason_code,
        "trade_date": "2025-01-21",
        "authority": {"status": authority_status, "run_id": None, "snapshot_id": None},
        "jin10": "not_used",
    }
    assert not (tmp_path / "analysis").exists()
