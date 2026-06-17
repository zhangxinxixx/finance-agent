"""P4-10: Tests for sync_outputs_to_obsidian.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Import the module under test (must be importable)
import scripts.sync_outputs_to_obsidian as sync


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def fake_storage(tmp_path: Path) -> Path:
    """Create a minimal storage tree with one final report and one snapshot."""
    storage = tmp_path / "storage"

    # Final report
    report_dir = storage / "outputs" / "final_report" / "XAUUSD" / "2026-05-15" / "test-run-id"
    report_dir.mkdir(parents=True)
    report_md = report_dir / "final_report.md"
    report_md.write_text("# Final Report\n\nGold analysis summary.\n\n## Macro\n\nBullish signal.", encoding="utf-8")
    report_json = report_dir / "final_report.json"
    report_json.write_text(
        json.dumps(
            {
                "snapshot_id": "XAUUSD:2026-05-15:test-run-id",
                "status": "success",
                "coordinator_bias": "bullish",
                "confidence": 0.72,
                "source_refs": [{"source": "cme"}],
                "market_phase": "trend_tailwind",
                "market_odds": {"status": "partial", "aggregate_signal": "bullish"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Analysis snapshot
    snap_dir = storage / "features" / "snapshots" / "XAUUSD" / "2026-05-15" / "snap-run-id"
    snap_dir.mkdir(parents=True)
    snap_json = snap_dir / "premarket_snapshot.json"
    snap_json.write_text(
        json.dumps(
            {
                "snapshot_id": "XAUUSD:2026-05-15:snap-run-id",
                "status": "success",
                "source_refs": [{"source": "fred"}],
                "macro": {"status": "available"},
                "options": {"status": "available", "data_source": {"status": "PRELIMINARY"}},
                "market_odds": {"status": "partial", "aggregate_signal": "neutral"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return storage


@pytest.fixture
def fake_vault(tmp_path: Path) -> Path:
    """Create a minimal vault."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


# ── Dry-run tests ───────────────────────────────────────────────────────


def test_dry_run_does_not_write(fake_storage, fake_vault):
    result = sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=True,
    )
    assert result["synced"] > 0
    # No files should be written
    notes_dir = fake_vault / sync.ANALYSIS_RECORDS_DIR
    assert not notes_dir.exists() or not any(notes_dir.iterdir())


def test_dry_run_reports_correct_counts(fake_storage, fake_vault):
    result = sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=True,
    )
    assert result["synced"] >= 1
    assert "reports" in result


def test_real_write_creates_files(fake_storage, fake_vault):
    result = sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=False,
    )
    assert result["synced"] > 0
    notes_dir = fake_vault / sync.ANALYSIS_RECORDS_DIR
    assert notes_dir.exists()
    files = list(notes_dir.iterdir())
    assert len(files) >= 1
    content = files[0].read_text(encoding="utf-8")
    assert "分析快照" in content or "Final Report" in content


# ── Safety tests ────────────────────────────────────────────────────────


def test_no_overwrite_by_default(fake_storage, fake_vault):
    # First write
    sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=False,
    )
    notes_dir = fake_vault / sync.ANALYSIS_RECORDS_DIR
    first_mtime = list(notes_dir.iterdir())[0].stat().st_mtime

    # Second write without --overwrite
    sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=False,
        overwrite=False,
    )
    second_mtime = list(notes_dir.iterdir())[0].stat().st_mtime

    assert first_mtime == second_mtime, "Existing note should not be overwritten"


def test_overwrite_flag_allows_rewrite(fake_storage, fake_vault):
    # First write with dry_run=False, files should exist
    sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=False,
    )
    notes_dir = fake_vault / sync.ANALYSIS_RECORDS_DIR
    files_before = sorted(notes_dir.iterdir())
    assert len(files_before) >= 1

    # Overwrite should not create additional files, just rewrite existing
    # Verify no exception is raised (the sync completes)
    sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=False,
        overwrite=True,
    )
    files_after = sorted(notes_dir.iterdir())
    # Same number of files (no dupes), and the files still exist
    assert len(files_after) == len(files_before)


def test_vault_not_found(tmp_path):
    result = sync.sync_to_obsidian(
        storage_root=tmp_path / "storage",
        vault_root=tmp_path / "nonexistent_vault",
    )
    assert "error" in result
    assert result["synced"] == 0


def test_storage_not_found(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    result = sync.sync_to_obsidian(
        storage_root=tmp_path / "nonexistent_storage",
        vault_root=vault,
    )
    assert "error" in result


def test_path_escape_prevention(tmp_path):
    """Path with dots/slashes is sanitized and stays inside vault."""
    vault = tmp_path / "vault"
    vault.mkdir()

    path = sync._build_note_path(
        vault,
        {"trade_date": "../../../etc", "run_id": "test", "type": "final_report"},
    )
    # _safe_component replaces '/' with '_', so the path is safe but not None
    assert path is not None, "Sanitized path should be valid"
    # The resolved path must stay inside the vault
    assert str(path.resolve()).startswith(str(vault.resolve())), "Path must be inside vault"


def test_max_entries_limit(fake_storage, fake_vault):
    result = sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=True,
        max_entries=1,
    )
    assert result["reports"] <= 1


# ── Content tests ───────────────────────────────────────────────────────


def test_note_contains_metadata(fake_storage, fake_vault):
    sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=False,
    )
    notes_dir = fake_vault / sync.ANALYSIS_RECORDS_DIR
    for note_file in notes_dir.iterdir():
        content = note_file.read_text(encoding="utf-8")
        assert "snapshot_id" in content
        assert "trade_date" in content
        assert "run_id" in content
        assert "P4-10" in content or "同步脚本" in content or "sync_outputs" in content


def test_note_does_not_contain_raw_data(fake_storage, fake_vault):
    """Notes should not contain raw CME PDF paths or large JSON dumps."""
    sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=False,
    )
    notes_dir = fake_vault / sync.ANALYSIS_RECORDS_DIR
    for note_file in notes_dir.iterdir():
        content = note_file.read_text(encoding="utf-8")
        assert ".pdf" not in content.lower(), "Raw PDF paths should not be synced"
        assert "open_interest" not in content, "Raw option data should not be synced"


def test_index_generated(fake_storage, fake_vault):
    """After real write, the index file should exist."""
    sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=False,
    )
    index_path = fake_vault / sync.OUTPUT_INDEX_DIR / "报告索引.md"
    assert index_path.exists()
    content = index_path.read_text(encoding="utf-8")
    assert "报告索引" in content


# ── Edge cases ───────────────────────────────────────────────────────────


def test_empty_storage(tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    result = sync.sync_to_obsidian(storage_root=storage, vault_root=vault)
    assert result["synced"] == 0


def test_report_without_json_present(fake_storage, fake_vault):
    """Reports without .json sidecar should still be synced."""
    sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=False,
    )
    # The report in fake_storage has a .json — remove it and re-sync
    report_dir = fake_storage / "outputs" / "final_report" / "XAUUSD" / "2026-05-15" / "test-run-id"
    (report_dir / "final_report.json").unlink()
    result = sync.sync_to_obsidian(
        storage_root=fake_storage,
        vault_root=fake_vault,
        dry_run=True,
        overwrite=True,
        max_entries=5,
    )
    assert result["reports"] >= 1
