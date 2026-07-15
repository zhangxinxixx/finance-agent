from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cli_builds_snapshot_from_macro_and_options_json(tmp_path: Path):
    macro_json = tmp_path / "macro.json"
    options_json = tmp_path / "options.json"
    macro_json.write_text(
        json.dumps(
            {
                "as_of": "2026-05-14",
                "indicators": {"DGS10": {"date": "2026-05-14", "value": 4.3}},
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        ),
        encoding="utf-8",
    )
    options_json.write_text(
        json.dumps(
            {
                "trade_date": "2026-05-14",
                "data_source": {"input_snapshot_ids": {"raw_file_sha256": "abc123"}},
                "wall_scores": [{"strike": 3300}],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_analysis_snapshot.py",
            "--asset",
            "XAUUSD",
            "--trade-date",
            "2026-05-14",
            "--run-id",
            "smoke",
            "--macro-json",
            str(macro_json),
            "--options-json",
            str(options_json),
            "--storage-root",
            str(tmp_path),
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    snapshot_path = tmp_path / "features/snapshots/XAUUSD/2026-05-14/smoke/premarket_snapshot.json"
    assert str(snapshot_path) in result.stdout
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["snapshot_id"] == "XAUUSD:2026-05-14:smoke"
    assert snapshot["macro"]["status"] == "available"
    assert snapshot["options"]["status"] == "available"
    assert snapshot["input_snapshot_ids"]["options_detail"] == {"raw_file_sha256": "abc123"}


def test_cli_fails_fast_when_input_missing_without_allow_missing(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_analysis_snapshot.py",
            "--asset",
            "XAUUSD",
            "--trade-date",
            "2026-05-14",
            "--run-id",
            "missing",
            "--macro-json",
            str(tmp_path / "missing-macro.json"),
            "--options-json",
            str(tmp_path / "missing-options.json"),
            "--storage-root",
            str(tmp_path),
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "does not exist" in result.stderr


def test_cli_allows_missing_inputs_when_explicitly_requested(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_analysis_snapshot.py",
            "--asset",
            "XAUUSD",
            "--trade-date",
            "2026-05-14",
            "--run-id",
            "allow-missing",
            "--macro-json",
            str(tmp_path / "missing-macro.json"),
            "--options-json",
            str(tmp_path / "missing-options.json"),
            "--storage-root",
            str(tmp_path),
            "--allow-missing",
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    snapshot_path = tmp_path / "features/snapshots/XAUUSD/2026-05-14/allow-missing/premarket_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["macro"] == {"status": "unavailable", "reason": "input_not_available"}
    assert snapshot["options"] == {"status": "unavailable", "reason": "input_not_available"}
