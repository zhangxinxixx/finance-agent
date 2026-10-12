from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from database.models.execution import ExecutionEvent
from database.models.report import ReportItem
from scripts import prune_unqualified_outputs as cli
from tests.data_layer.test_output_retention import _factory, _seed_run


def test_cli_defaults_to_dry_run_without_database_writes(tmp_path: Path, capsys) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root)

    rc = cli.main(
        ["--storage-root", str(root), "--run-id", run_id],
        session_factory=factory,
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["dry_run"] is True
    assert payload["candidate_run_count"] == 1
    assert path.exists()
    with factory() as session:
        assert session.get(ReportItem, f"final_report:{run_id}").data_status == "live"
        assert session.scalar(select(func.count()).select_from(ExecutionEvent)) == 0


def test_cli_apply_requires_explicit_run_id(tmp_path: Path, capsys) -> None:
    root = tmp_path / "storage"
    root.mkdir()

    rc = cli.main(["--storage-root", str(root), "--apply"], session_factory=lambda: None)

    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload == {
        "dry_run": False,
        "error_code": "OUTPUT_CLEANUP_RUN_IDS_REQUIRED",
    }


def test_cli_uses_only_database_url_environment(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DOTENV_PATH", "/must/not/be/read/.env")

    rc = cli.main(["--storage-root", str(root)])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["error_code"] == "OUTPUT_CLEANUP_DATABASE_URL_REQUIRED"
    assert ".env" not in capsys.readouterr().out


def test_cli_masks_unexpected_database_error(tmp_path: Path, capsys) -> None:
    root = tmp_path / "storage"
    root.mkdir()

    class BrokenFactory:
        def __call__(self):
            raise RuntimeError("postgresql://user:secret@example.invalid/db")

    rc = cli.main(["--storage-root", str(root)], session_factory=BrokenFactory())

    output = capsys.readouterr().out
    assert rc == 2
    assert json.loads(output)["error_code"] == "OUTPUT_CLEANUP_FAILED"
    assert "secret" not in output
