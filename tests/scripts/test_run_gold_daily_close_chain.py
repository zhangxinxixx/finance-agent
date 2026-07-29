from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from apps.analysis.gold_policy.daily_close_store import DailyCloseHeadConflictError
from scripts import run_gold_daily_close_chain as cli
from tests.analysis.test_gold_daily_close_batch import _batch


_SCRIPT = Path(__file__).parents[2] / "scripts" / "run_gold_daily_close_chain.py"


def test_cli_prints_machine_readable_fixture_readiness(tmp_path: Path) -> None:
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(
        json.dumps(_batch().model_dump(mode="json")), encoding="utf-8"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--input",
            str(batch_path),
            "--storage-root",
            str(tmp_path / "storage"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["sample_count"] == 5
    assert payload["readiness"] == "insufficient_sample"
    assert payload["evidence_scope"] == "fixture_or_replay_only"
    assert payload["analysis_memory_production_canonical"] is False


def test_cli_fails_closed_for_malformed_json(tmp_path: Path) -> None:
    batch_path = tmp_path / "invalid.json"
    batch_path.write_text("{not-json", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--input",
            str(batch_path),
            "--storage-root",
            str(tmp_path / "storage"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    payload = json.loads(completed.stderr)
    assert payload["status"] == "error"
    assert "JSONDecodeError" in payload["error"]


def test_cli_fails_closed_for_store_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    batch_path = tmp_path / "batch.json"
    batch_path.write_text(
        json.dumps(_batch().model_dump(mode="json")), encoding="utf-8"
    )

    def fail_conflict(**_kwargs):
        raise DailyCloseHeadConflictError("controlled predecessor conflict")

    monkeypatch.setattr(cli, "execute_gold_daily_close_batch", fail_conflict)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(_SCRIPT),
            "--input",
            str(batch_path),
            "--storage-root",
            str(tmp_path / "storage"),
        ],
    )
    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload == {
        "status": "error",
        "error": "DailyCloseHeadConflictError: controlled predecessor conflict",
    }
