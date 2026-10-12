"""Official target range from the Fed's dated Open Market Operations table.

The table supplies dates, not intraday publication/effectiveness times. We use
the end of the stated US Eastern day as a conservative availability boundary.
It cannot establish an intraday FOMC transition or a historical page vintage.
"""

import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup


def parse_fed_target(html, *, as_of, source_refs):
    cutoff = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    if cutoff.tzinfo is None or not source_refs:
        raise ValueError("target_requires_aware_cutoff_and_provenance")
    soup = BeautifulSoup(html, "html.parser")
    match = re.search(r"Last Update:\s*([A-Za-z]+ \d{1,2}, \d{4})", soup.get_text(" ", strip=True))
    if not match:
        raise ValueError("fed_target_publication_date_missing")

    def day_end(day):
        return (datetime.combine(day + timedelta(days=1), time(), ZoneInfo("America/New_York"))
                - timedelta(microseconds=1)).astimezone(UTC)

    published = day_end(datetime.strptime(match[1], "%B %d, %Y").date())
    if published > cutoff:
        raise ValueError("fed_target_page_vintage_after_cutoff")
    rows = []
    for table in soup.select("table.pubtables"):
        heading = table.find_previous("h4")
        year = heading.get_text(strip=True) if heading else ""
        if not re.fullmatch(r"20\d\d", year):
            continue
        headers = [h.get_text(" ", strip=True) for h in table.select("thead th")]
        if headers != ["Date", "Increase", "Decrease", "Level (%)"]:
            raise ValueError("fed_target_table_schema_changed")
        for row in table.select("tbody tr"):
            cells = [c.get_text(" ", strip=True) for c in row.select("td")]
            if len(cells) != 4:
                raise ValueError("fed_target_row_schema_changed")
            bounds = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", cells[3])
            if not bounds:  # Pre-2008 single-rate regime is not a target range.
                continue
            low, high = map(float, bounds.groups())
            if not 0 <= low < high <= 30 or high - low > 1:
                raise ValueError("fed_target_invalid_range")
            day = datetime.strptime(f"{cells[0].rstrip('*')} {year}", "%B %d %Y").date()
            effective = day_end(day)
            if day == cutoff.astimezone(ZoneInfo("America/New_York")).date() and effective > cutoff:
                raise ValueError("fed_target_intraday_effectiveness_unverified")
            if effective <= cutoff:
                rows.append((effective, low, high, day))
    if not rows:
        raise ValueError("fed_target_no_effective_range")
    effective, low, high, day = max(rows)
    return {"lower": low, "upper": high, "rate_unit": "percent",
            "effective_at": effective.isoformat(), "published_at": published.isoformat(),
            "effective_date": day.isoformat(), "timestamp_precision": "date",
            "availability_convention": "conservative_end_of_source_day_America_New_York",
            "historical_vintage_verified": False, "source_refs": source_refs}
