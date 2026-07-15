from __future__ import annotations

import json

from sqlalchemy import create_engine

from database.models.analysis import ensure_analysis_tables
from scripts import run_xauusd_shadow_summary as script


def test_cli_dry_run_uses_explicit_date_storage_database_and_output(tmp_path, capsys):
    database_path = tmp_path / "shadow.db"
    database_url = f"sqlite:///{database_path}"
    ensure_analysis_tables(create_engine(database_url))
    output = tmp_path / "custom" / "summary.json"

    rc = script.main(
        [
            "--date",
            "2026-07-16",
            "--storage-root",
            str(tmp_path / "storage"),
            "--database-url",
            database_url,
            "--output",
            str(output),
            "--dry-run",
            "--as-of",
            "2026-07-16T12:00:00Z",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["dry_run"] is True
    assert payload["output_path"] == str(output)
    assert output.exists() is False
    assert payload["summary"]["finalization"]["finalized"] is False
