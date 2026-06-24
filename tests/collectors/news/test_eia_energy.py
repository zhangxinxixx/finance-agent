from __future__ import annotations

from pathlib import Path

import httpx

from apps.collectors.news.eia import collect_eia_energy_events


EIA_SCHEDULE_FIXTURE = """
<html>
  <body>
    <table class="schedule">
      <tr>
        <th>Data for the week ending</th>
        <th>Alternate release date</th>
        <th>Release day</th>
        <th>Release time</th>
        <th>Holiday</th>
      </tr>
      <tr>
        <th scope="row">September 4, 2026</th>
        <td>September 10, 2026</td>
        <td>Thursday</td>
        <td>12:00 p.m.</td>
        <td>Labor Day</td>
      </tr>
      <tr>
        <th scope="row">October 9, 2026</th>
        <td>October 15, 2026</td>
        <td>Thursday</td>
        <td>12:00 p.m.</td>
        <td>Columbus Day</td>
      </tr>
    </table>
  </body>
</html>
"""


def test_eia_energy_events_maps_wpsr_release_schedule(tmp_path: Path) -> None:
    response = httpx.Response(
        200,
        content=EIA_SCHEDULE_FIXTURE.encode("utf-8"),
        request=httpx.Request("GET", "https://eia.test/schedule.php"),
    )

    result = collect_eia_energy_events(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        schedule_url="https://eia.test/schedule.php",
        client=type("Client", (), {"get": lambda self, url: response})(),
    )

    assert result.status == "success"
    assert len(result.items) == 2
    item = result.items[0]
    assert item.source_key == "eia_energy"
    assert item.source_type == "official"
    assert item.title == "Weekly Petroleum Status Report"
    assert item.summary == "Data for the week ending September 4, 2026; holiday: Labor Day"
    assert item.published_at == "2026-09-10T16:00:00+00:00"
    assert item.event_type == "energy_inventory_release"
    assert item.verification_status == "official_confirmed"
    assert item.raw_path.startswith("raw/news/eia/2026-06-10/weekly_petroleum_status_report-")
    assert item.parsed_path.startswith("parsed/news/eia/2026-06-10/weekly_petroleum_status_report-")
    assert (tmp_path / item.raw_path).exists()
    assert (tmp_path / item.parsed_path).exists()


def test_eia_energy_events_marks_unavailable_when_request_fails(tmp_path: Path) -> None:
    client = type("Client", (), {"get": lambda self, url: (_ for _ in ()).throw(httpx.ConnectError("offline"))})()

    result = collect_eia_energy_events(
        retrieved_date="2026-06-10",
        storage_root=tmp_path,
        schedule_url="https://eia.test/schedule.php",
        client=client,
    )

    assert result.status == "unavailable"
    assert result.items == []
    assert result.unavailable_feeds == ["weekly_petroleum_status_report"]
