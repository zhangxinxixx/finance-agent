from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

from apps.parsers.cme.pdf_parser import parse_pg64_pdf


PDF_PATH = Path("storage/raw/cme/daily_bulletin/2026-05-06/Section64_Metals_Option_Products_2026-05-06.pdf")


def _resolve_pdf_path() -> Path:
    if PDF_PATH.exists():
        return PDF_PATH
    fallback = Path("/tmp/finance-agent/workspace/finance-agent/storage/raw/cme/daily_bulletin/2026-05-06/Section64_Metals_Option_Products_2026-05-06.pdf")
    assert fallback.exists(), fallback
    return fallback


def _sum_rows(detail_rows):
    bucket = defaultdict(int)
    for row in detail_rows:
        key = (row.expiry, row.option_type)
        bucket[(key, "open_interest")] += int(row.open_interest or 0)
        bucket[(key, "oi_change")] += int(row.oi_change or 0)
        bucket[(key, "total_volume")] += int(row.total_volume or 0)
        bucket[(key, "block_volume")] += int(row.block_volume or 0)
        bucket[(key, "pnt_volume")] += int(row.pnt_volume or 0)
        bucket[(key, "globex_volume")] += int(row.globex_volume or 0)
        bucket[(key, "outcry_volume")] += int(row.outcry_volume or 0)
        bucket[(key, "exercises")] += int(row.exercises or 0)
    return bucket


def test_parse_pg64_pdf_extracts_og_rows_and_summary_matches_detail() -> None:
    result = parse_pg64_pdf(_resolve_pdf_path(), product="OG", expiries={"JUN26", "JUL26"})
    detail_by_key = {(row.expiry, row.option_type, row.strike): row for row in result.detail_rows}
    keys = [(row.product, row.expiry, row.strike, row.option_type) for row in result.detail_rows]

    assert result.trade_date == "2026-05-06"
    assert result.status == "PRELIMINARY"
    assert result.bulletin == "PG64 Bulletin #86"
    assert result.detail_rows
    assert result.summary_rows
    assert len(keys) == len(set(keys))
    assert any(row.expiry == "JUN26" for row in result.detail_rows)
    assert any(row.expiry == "JUL26" for row in result.detail_rows)
    assert any(row.option_type == "CALL" for row in result.detail_rows)
    assert any(row.option_type == "PUT" for row in result.detail_rows)
    assert sum(row.block_volume or 0 for row in result.detail_rows) > 0
    assert detail_by_key[("JUN26", "CALL", 3700)].settlement == pytest.approx(994.9, rel=1e-4)
    assert detail_by_key[("JUL26", "CALL", 3700)].settlement == pytest.approx(1032.4, rel=1e-4)
    assert detail_by_key[("JUN26", "CALL", 3700)].open_interest == 389
    assert detail_by_key[("JUN26", "CALL", 4700)].block_volume == 100
    assert detail_by_key[("JUN26", "CALL", 4950)].block_volume == 200
    assert detail_by_key[("JUL26", "CALL", 4700)].block_volume == 40
    assert detail_by_key[("JUN26", "PUT", 4350)].block_volume == 15
    assert result.notes["block_rule"].startswith("block_volume only from OPTIONS EOO'S AND BLOCKS")

    first = result.detail_rows[0].to_dict()
    assert set(first) == {
        "trade_date",
        "product",
        "expiry",
        "strike",
        "option_type",
        "settlement",
        "delta",
        "open_interest",
        "oi_change",
        "total_volume",
        "block_volume",
        "pnt_volume",
        "globex_volume",
        "outcry_volume",
        "exercises",
        "pt_change",
    }
    assert first["trade_date"] == "2026-05-06"
    assert first["product"] == "OG"
    assert first["strike"] > 0

    summary_map = {(row.expiry, row.option_type): row for row in result.summary_rows}
    expected = _sum_rows(result.detail_rows)
    for key, summary in summary_map.items():
        for field in ["open_interest", "oi_change", "total_volume", "block_volume", "pnt_volume", "globex_volume", "outcry_volume", "exercises"]:
            assert getattr(summary, field) == expected[(key, field)]


def test_parse_pg64_pdf_filters_expiries() -> None:
    result = parse_pg64_pdf(_resolve_pdf_path(), product="OG", expiries={"JUN26"})
    assert result.detail_rows
    assert {row.expiry for row in result.detail_rows} == {"JUN26"}
    assert {row.expiry for row in result.summary_rows} == {"JUN26"}


def test_parse_cme_pdf_cli_writes_json_and_csv(tmp_path: Path) -> None:
    out_dir = tmp_path / "parsed"
    cmd = [
        sys.executable,
        "scripts/parse_cme_pdf.py",
        "--pdf",
        str(_resolve_pdf_path()),
        "--product",
        "OG",
        "--expiries",
        "JUN26,JUL26",
        "--out-dir",
        str(out_dir),
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout.strip())
    json_path = Path(payload["json_path"])
    csv_path = Path(payload["csv_path"])
    assert json_path.exists()
    assert csv_path.exists()
    assert payload["rows"] > 0

    with json_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["trade_date"] == "2026-05-06"
    assert data["detail_rows"]
    detail_keys = [
        (row["product"], row["expiry"], row["strike"], row["option_type"])
        for row in data["detail_rows"]
    ]
    assert len(detail_keys) == len(set(detail_keys))
    assert any(
        row["expiry"] == "JUN26"
        and row["option_type"] == "CALL"
        and int(row["strike"]) == 3700
        and pytest.approx(994.9, rel=1e-4) == float(row["settlement"])
        for row in data["detail_rows"]
    )
    assert any(
        row["expiry"] == "JUL26"
        and row["option_type"] == "CALL"
        and int(row["strike"]) == 3700
        and pytest.approx(1032.4, rel=1e-4) == float(row["settlement"])
        for row in data["detail_rows"]
    )
    assert sum(int(row["block_volume"] or 0) for row in data["summary_rows"]) > 0

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert rows[0]["trade_date"] == "2026-05-06"
    assert any(int(row["block_volume"] or 0) > 0 for row in rows)
