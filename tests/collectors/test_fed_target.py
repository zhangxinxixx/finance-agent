from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from apps.collectors.fed.target import SOURCE_URL, collect_fed_target
from apps.parsers.macro.fed_target import parse_fed_target

HTML = (Path(__file__).parents[1] / "fixtures/fed_target/openmarket-excerpt.html").read_text()
REF = [{"source": "federal_reserve_target", "source_url": SOURCE_URL}]


def test_actual_official_table_and_date_precision():
    value = parse_fed_target(HTML, as_of="2026-09-28T12:00:00+00:00", source_refs=REF)
    assert (value["lower"], value["upper"]) == (3.75, 4)
    assert value["effective_date"] == "2026-09-17"
    assert value["timestamp_precision"] == "date"
    assert value["effective_at"].startswith("2026-09-18T03:59:59")


@pytest.mark.parametrize("text,at", [(HTML.replace("Level (%)", "Rate"), "2026-09-28T12:00:00Z"),
                                    (HTML, "2026-09-15T12:00:00Z"),
                                    (HTML.replace("3.75-4.00", "4.00-3.75"), "2026-09-28T12:00:00Z")])
def test_drift_future_and_invalid_ranges_fail_closed(text, at):
    with pytest.raises(ValueError):
        parse_fed_target(text, as_of=at, source_refs=REF)


def test_collector_archives_success_and_failure_immutably(tmp_path):
    now = datetime(2026, 9, 28, 12, tzinfo=UTC)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=HTML))) as client:
        first = collect_fed_target(storage_root=tmp_path, client=client, now=now)
        second = collect_fed_target(storage_root=tmp_path, client=client, now=now)
    assert first["status"] == "available"
    assert first["raw_artifact_ref"] != second["raw_artifact_ref"]
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, text="Unavailable"))) as client:
        failed = collect_fed_target(storage_root=tmp_path, client=client, now=now)
    assert failed["status"] == "unavailable"
    assert (tmp_path / failed["raw_artifact_ref"]).exists()
