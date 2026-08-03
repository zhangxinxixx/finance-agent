"""Registry sink tests for the verified Gold Policy daily-close bundle."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.analysis.gold_policy.daily_close_store import verify_gold_daily_close_bundle
from apps.worker.report_registry_sink import (
    GoldPolicyReportRegistryError,
    _map_gold_policy_publication_status,
    register_gold_policy_report_bundle,
)
from database.models.analysis import ensure_analysis_tables
from database.models.report import ReportArtifact, ReportItem, ensure_report_tables


_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "gold_daily_report"
_FIXTURE_NAME = "premarket_snapshot_2026-07-07.json"
_FIXTURE_PATH = _FIXTURE_DIR / _FIXTURE_NAME
_FIXTURE_SOURCE_SHA256 = "85dd2f24075812d62206ee12d1e5fea37d892e3cb2c9360a3c73d0a3e07a4d97"

_REPORT_FILES = (
    "source.md",
    "analysis.md",
    "visual.html",
    "report_structured.json",
    "evidence.json",
    "data_quality.json",
    "report_manifest.json",
    "strategy_card.json",
    "strategy_card.md",
)


def _make_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _materialize_snapshot(tmp_path: Path) -> tuple[Path, str]:
    fixture_bytes = _FIXTURE_PATH.read_bytes()
    digest = hashlib.sha256(fixture_bytes).hexdigest()
    assert digest == _FIXTURE_SOURCE_SHA256, f"fixture sha mismatch: {digest}"
    payload = json.loads(fixture_bytes.decode("utf-8"))
    trade_date = payload["trade_date"]
    run_id = payload["run_id"]
    snapshot_dir = tmp_path / "features" / "snapshots" / "XAUUSD" / trade_date / run_id
    snapshot_dir.mkdir(parents=True)
    target = snapshot_dir / "premarket_snapshot.json"
    target.write_bytes(fixture_bytes)
    return target, trade_date


def _run_with_jin10_disabled(tmp_path: Path, trade_date: str) -> dict:
    from scripts import run_gold_daily_report as report

    previous = os.environ.get("FINANCE_AGENT_DISABLE_JIN10")
    os.environ["FINANCE_AGENT_DISABLE_JIN10"] = "true"
    try:
        return report.run_gold_daily_report(
            trade_date=trade_date,
            storage_root=tmp_path,
        )
    finally:
        if previous is None:
            os.environ.pop("FINANCE_AGENT_DISABLE_JIN10", None)
        else:
            os.environ["FINANCE_AGENT_DISABLE_JIN10"] = previous


def _materialize_verified_bundle(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """Materialize a real v2 bundle from the frozen fixture and return paths."""

    _materialize_snapshot(tmp_path)
    # Use a copy of tmp_path to avoid cross-test contamination of the snapshot
    # directory layout; run_gold_daily_report only needs storage_root.
    result = _run_with_jin10_disabled(tmp_path, "2026-07-07")
    assert result["status"] == "completed", result
    report_paths = [Path(path) for path in result["report_paths"]]
    bundle_path = report_paths[0].parent
    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=bundle_path,
    )
    assert verification.status == "valid", verification
    return tmp_path, bundle_path, result["trade_date"], result["run_id"]


def test_register_gold_policy_report_bundle_persists_one_item_and_nine_artifacts(
    tmp_path: Path,
) -> None:
    storage_root, bundle_path, trade_date, run_id = _materialize_verified_bundle(tmp_path)

    factory = _make_session_factory()
    with factory() as db:
        report_id = register_gold_policy_report_bundle(
            db,
            storage_root=storage_root,
            bundle_path=bundle_path,
        )
        db.commit()

    expected_report_id = f"gold_policy_daily:{trade_date}:{run_id}"
    assert report_id == expected_report_id

    with factory() as db:
        items = db.query(ReportItem).filter(ReportItem.report_id == report_id).all()
        assert len(items) == 1
        item = items[0]
        assert item.family == "gold_policy_daily_report"
        assert item.report_type == "gold_policy_daily"
        assert item.asset == "XAUUSD"
        assert item.trade_date.isoformat() == trade_date
        assert item.run_id == run_id
        assert item.source_refs
        assert item.report_metadata["writer"] == "register_gold_policy_report_bundle"
        assert item.report_metadata["canonical_receipt_id"]
        assert item.report_metadata["manifest_schema_version"] == "gold_policy_report_manifest.v2"

        artifacts = (
            db.query(ReportArtifact)
            .filter(ReportArtifact.report_id == report_id)
            .order_by(ReportArtifact.artifact_id)
            .all()
        )
        assert len(artifacts) == 9
        assert {artifact.file_path.split("/")[-1] for artifact in artifacts} == set(_REPORT_FILES)
        assert sum(1 for artifact in artifacts if artifact.is_primary) == 1
        primary = next(artifact for artifact in artifacts if artifact.is_primary)
        assert primary.artifact_type == "analysis_md"
        assert primary.content_type == "text/markdown"
        assert primary.sha256 and len(primary.sha256) == 64
        assert primary.byte_size is not None and primary.byte_size > 0
        assert primary.storage_backend == "local_fs"

        for artifact in artifacts:
            assert artifact.sha256
            assert artifact.byte_size is not None and artifact.byte_size > 0
            assert artifact.content_type
            assert artifact.source_refs
            assert artifact.artifact_metadata["receipt_id"]
            assert artifact.artifact_metadata["canonical_commit_action"]

        data_quality = json.loads((bundle_path / "data_quality.json").read_text(encoding="utf-8"))
        publication_status = data_quality["publication_status"]
        if publication_status == "accepted":
            assert item.data_status == "live"
            assert item.lifecycle_status == "snapshot_bound"
        else:
            assert item.data_status == "partial"
            assert item.lifecycle_status == "needs_review"

        # v2 source_refs carry reference/retrieved_at; the sink must preserve
        # real lineage by mapping them to source_ref/captured_at rather than
        # degenerating to the bare source name.
        evidence = json.loads((bundle_path / "evidence.json").read_text(encoding="utf-8"))
        raw_source_refs = evidence.get("source_refs", [])
        raw_refs_with_reference = [ref for ref in raw_source_refs if isinstance(ref, dict) and ref.get("reference")]
        raw_refs_with_retrieved_at = [
            ref for ref in raw_source_refs if isinstance(ref, dict) and ref.get("retrieved_at")
        ]
        assert raw_refs_with_reference, "fixture should expose at least one v2 ref with reference"
        assert raw_refs_with_retrieved_at, "fixture should expose at least one v2 ref with retrieved_at"

        persisted_refs = item.source_refs
        assert persisted_refs
        for ref in persisted_refs:
            if isinstance(ref, dict) and ref.get("reference"):
                assert ref["source_ref"] == ref["reference"]
            if isinstance(ref, dict) and ref.get("retrieved_at"):
                assert ref["captured_at"] == ref["retrieved_at"]

        ref_with_reference_count = sum(
            1 for ref in persisted_refs if isinstance(ref, dict) and ref.get("source_ref") == ref.get("reference")
        )
        assert ref_with_reference_count >= 1, (
            "no persisted source_ref matches a v2 reference; lineage degenerated to source name"
        )

        # SHA-256 sanity: registry sha matches filesystem sha
        for artifact in artifacts:
            path = Path(artifact.file_path)
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256


def test_register_gold_policy_report_bundle_is_idempotent(tmp_path: Path) -> None:
    storage_root, bundle_path, trade_date, run_id = _materialize_verified_bundle(tmp_path)
    factory = _make_session_factory()

    first_id = ""
    with factory() as db:
        first_id = register_gold_policy_report_bundle(
            db,
            storage_root=storage_root,
            bundle_path=bundle_path,
        )
        db.commit()

    with factory() as db:
        second_id = register_gold_policy_report_bundle(
            db,
            storage_root=storage_root,
            bundle_path=bundle_path,
        )
        db.commit()

    assert first_id == second_id

    with factory() as db:
        items = db.query(ReportItem).filter(ReportItem.report_id == first_id).all()
        artifacts = db.query(ReportArtifact).filter(ReportArtifact.report_id == first_id).all()
        assert len(items) == 1
        assert len(artifacts) == 9


def test_register_gold_policy_report_bundle_fails_closed_when_analysis_md_tampered(
    tmp_path: Path,
) -> None:
    storage_root, bundle_path, _, _ = _materialize_verified_bundle(tmp_path)

    tampered_target = tmp_path / "tampered_bundle"
    _copy_bundle(bundle_path, tampered_target)
    analysis_md = tampered_target / "analysis.md"
    original_bytes = analysis_md.read_bytes()
    tampered_bytes = original_bytes + b"\n<!-- tampered -->\n"
    analysis_md.write_bytes(tampered_bytes)

    factory = _make_session_factory()
    with factory() as db:
        with pytest.raises(GoldPolicyReportRegistryError):
            register_gold_policy_report_bundle(
                db,
                storage_root=storage_root,
                bundle_path=tampered_target,
            )
        db.commit()

    with factory() as db:
        items = db.query(ReportItem).all()
        artifacts = db.query(ReportArtifact).all()
        assert len(items) == 0
        assert len(artifacts) == 0

    # Ensure the file is not "repaired" by the failed registration attempt
    assert analysis_md.read_bytes() == tampered_bytes


def test_register_gold_policy_report_bundle_fails_closed_when_manifest_schema_unknown(
    tmp_path: Path,
) -> None:
    storage_root, bundle_path, _, _ = _materialize_verified_bundle(tmp_path)

    tampered_target = tmp_path / "tampered_manifest_bundle"
    _copy_bundle(bundle_path, tampered_target)
    manifest_path = tampered_target / "report_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "gold_policy_report_manifest.unknown"
    # Re-canonicalize so the report_manifest.json file itself stays parseable;
    # the bundle manifest (.bundle-manifest.json) still records the original
    # sha256, so verify_gold_daily_close_bundle returns status != "valid" and
    # the registry sink fail-closes with GoldPolicyReportRegistryError before
    # any DB write.
    new_manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path.write_bytes(new_manifest_bytes)

    factory = _make_session_factory()
    with factory() as db:
        with pytest.raises(GoldPolicyReportRegistryError):
            register_gold_policy_report_bundle(
                db,
                storage_root=storage_root,
                bundle_path=tampered_target,
            )
        db.commit()

    with factory() as db:
        items = db.query(ReportItem).all()
        artifacts = db.query(ReportArtifact).all()
        assert len(items) == 0
        assert len(artifacts) == 0


def test_register_gold_policy_report_bundle_returns_stable_report_id(tmp_path: Path) -> None:
    storage_root, bundle_path, trade_date, run_id = _materialize_verified_bundle(tmp_path)
    factory = _make_session_factory()

    with factory() as db:
        report_id = register_gold_policy_report_bundle(
            db,
            storage_root=storage_root,
            bundle_path=bundle_path,
        )
        db.commit()

    assert report_id == f"gold_policy_daily:{trade_date}:{run_id}"
    # Re-running registration must return the same stable id.
    with factory() as db:
        repeated = register_gold_policy_report_bundle(
            db,
            storage_root=storage_root,
            bundle_path=bundle_path,
        )
        db.commit()
    assert repeated == report_id


@pytest.mark.parametrize(
    "publication_status, expected",
    [
        ("accepted", ("live", "snapshot_bound")),
        ("observe", ("partial", "needs_review")),
        ("degraded", ("partial", "needs_review")),
    ],
)
def test_map_gold_policy_publication_status_returns_expected_tuple(
    publication_status: str,
    expected: tuple[str, str],
) -> None:
    assert _map_gold_policy_publication_status(publication_status) == expected


def test_map_gold_policy_publication_status_rejects_unknown_status() -> None:
    with pytest.raises(GoldPolicyReportRegistryError):
        _map_gold_policy_publication_status("unknown")


def _copy_bundle(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for path in source.iterdir():
        if not path.is_file():
            continue
        (destination / path.name).write_bytes(path.read_bytes())
