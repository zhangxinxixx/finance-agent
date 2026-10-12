"""Regression from an observed official table plus bounded transport failures."""
from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess

import pytest

from apps.collectors.macro.fedwatch_browser import collect_fedwatch_browser
from apps.parsers.macro.fedwatch_free import parse_fedwatch_free_payload
from apps.features.macro.fedwatch import build_fedwatch_health

FIXTURE = Path(__file__).parents[1] / "fixtures/fedwatch/20260928-official-cn-excerpt.html"
NOW = datetime(2026, 9, 28, 10, 10, tzinfo=timezone.utc)


def capture(pages, tabs=None, errors=None):
    return lambda: {"pages": [{"html": p} for p in pages], "meeting_tabs": tabs or len(pages),
                    "errors": errors or []}


def test_observed_nested_cn_table_and_two_row_header():
    result = parse_fedwatch_free_payload(FIXTURE.read_bytes(), content_type="text/html")
    assert result["as_of"] == "2026-09-28T10:00:34+00:00"
    current = [r for r in result["rows"] if r["comparison_window"] == "current"]
    assert sum(r["probability"] for r in current) == pytest.approx(1)
    assert next(r["probability"] for r in current if r["target_low"] == 4) == .703
    assert not any(r["target_low"] == 1 for r in current)  # blank is not zero
    assert {r["as_of"] for r in result["rows"] if r["comparison_window"] == "1d"} == {"2026-09-25T00:00:00+00:00"}
    assert {r["contract_ref"] for r in result["rows"]} == {"ZQV6"}


def test_archives_actual_pages_and_combines_distinct_meetings(tmp_path):
    first = FIXTURE.read_text()
    second = first.replace("28 10月 2026", "9 12月 2026").replace("ZQV6", "ZQZ6")
    result = collect_fedwatch_browser(storage_root=tmp_path, now=NOW, capture=capture([first, second]))
    assert result["parse_status"] == "ok"
    assert result["official_display_probability"] is True
    assert result["coverage"]["all_future_meetings"] is True
    assert len(result["coverage"]["meetings"]) == 2
    manifest = json.loads((tmp_path / result["raw_artifact_ref"]).read_text())
    assert len(manifest["responses"]) == 2
    assert manifest["capture_kind"] == "rendered_dom"
    assert manifest["responses"][0]["http_status"] is None
    assert (tmp_path / manifest["responses"][0]["raw_artifact_ref"]).read_text() == first


def test_duplicate_postback_does_not_create_false_meeting_coverage(tmp_path):
    first = FIXTURE.read_text()
    result = collect_fedwatch_browser(storage_root=tmp_path, now=NOW, capture=capture([first, first]))
    assert result["parse_status"] == "parse_failed"
    assert not result["rows"]
    assert len(result["source_refs"]) == 2


def test_partial_tabs_remain_explicit(tmp_path):
    result = collect_fedwatch_browser(storage_root=tmp_path, now=NOW,
                                    capture=capture([FIXTURE.read_text()], tabs=10, errors=["timeout"]))
    assert result["parse_status"] == "ok"
    assert not result["coverage"]["complete"]
    assert not result["coverage"]["all_future_meetings"]
    assert result["coverage"]["captured_tab_count"] == 1


def test_cross_meeting_time_mismatch_is_not_silently_merged(tmp_path):
    first = FIXTURE.read_text()
    second = first.replace("28 10月 2026", "9 12月 2026").replace("05:00:34", "05:10:34")
    result = collect_fedwatch_browser(storage_root=tmp_path, now=NOW, capture=capture([first, second]))
    assert result["parse_status"] == "parse_failed"
    assert not result["rows"]


def test_small_source_skew_preserves_each_timestamp_and_uses_oldest_for_age(tmp_path):
    first = FIXTURE.read_text()
    second = first.replace("28 10月 2026", "9 12月 2026").replace("05:00:34", "05:00:36")
    result = collect_fedwatch_browser(storage_root=tmp_path, now=NOW, capture=capture([first, second]))
    assert result["parse_status"] == "ok"
    assert result["as_of"] == "2026-09-28T10:00:36+00:00"
    assert len({r["as_of"] for r in result["rows"] if r["comparison_window"] == "current"}) == 2
    health = build_fedwatch_health(result, as_of=NOW.isoformat())
    assert health["status"] == "fresh"
    assert health["age_seconds"] == 566
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database.models.fedwatch import ensure_fedwatch_tables
    from database.queries.fedwatch import save_fedwatch_snapshot, get_latest_fedwatch_snapshot
    with Session(create_engine("sqlite://")) as session:
        ensure_fedwatch_tables(session)
        save_fedwatch_snapshot(session, result)
        loaded = get_latest_fedwatch_snapshot(session, as_of=NOW.isoformat())
        assert loaded["coverage"]["source_time_window"]["span_seconds"] == 2
        assert build_fedwatch_health(loaded, as_of=NOW.isoformat())["status"] == "fresh"


def test_real_far_meeting_thousands_and_absent_history():
    march = parse_fedwatch_free_payload((FIXTURE.parent / "20270317-official-cn-excerpt.html").read_bytes())
    assert any(r["target_high"] == 10 for r in march["rows"])
    december = parse_fedwatch_free_payload((FIXTURE.parent / "20271208-official-cn-excerpt.html").read_bytes())
    assert {r["comparison_window"] for r in december["rows"]} == {"current"}
    assert december["coverage"]["meetings"]["2027-12-08"]["missing_windows"] == ["1d", "1w", "1m"]


def test_native_failure_is_archived_without_raw_error_secrets(tmp_path):
    def failed():
        raise subprocess.CalledProcessError(1, ["sensitive-argument"], stderr=b"sensitive output")
    result = collect_fedwatch_browser(storage_root=tmp_path, now=NOW, capture=failed)
    assert result["parse_status"] == "missing"
    assert "sensitive" not in json.dumps(result)
    assert (tmp_path / result["raw_artifact_ref"]).is_file()
