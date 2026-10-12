"""Parse the Federal Reserve's official FOMC meeting calendar HTML."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlparse

from apps.collectors.news.base import RawNewsItem, stable_news_item_id

FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FOMC_SOURCE_KEY = "fomc_calendar"
FOMC_FEED_KEY = "fomc_meetings"
FOMC_SOURCE_NAME = "Federal Reserve FOMC Meeting Calendar"
FOMC_ACCESS_MODE = "direct_official_html"

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_YEAR_HEADING = re.compile(r"^(?P<year>\d{4})\s+FOMC\s+Meetings$", re.IGNORECASE)
_DATE_RANGE = re.compile(r"^(?P<start>\d{1,2})(?:\s*[-–—]\s*(?P<end>\d{1,2}))?(?P<note>.*)$")


class FOMCParseError(ValueError):
    """Raised when a calendar filter or meeting date is invalid."""


@dataclass(frozen=True)
class _FOMCMeeting:
    year: int
    month_label: str
    date_text: str
    start_date: date
    end_date: date
    is_sep: bool
    note: str | None
    links: tuple[str, ...]


def parse_fomc_calendar_html(
    html_text: str,
    *,
    fetched_at: str,
    source_url: str = FOMC_CALENDAR_URL,
    years: Iterable[int] | None = None,
    year: int | None = None,
    months: Iterable[int | str] | None = None,
    month: int | str | None = None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> list[RawNewsItem]:
    """Return scheduled FOMC meetings matching optional calendar filters.

    The official page publishes dates, not meeting times.  ``published_at``
    therefore contains the meeting's ISO start date only; no synthetic clock
    time is added.  An asterisk on the source date (SEP) is retained in the
    title and raw payload.
    """

    if not isinstance(html_text, str):
        raise FOMCParseError("FOMC calendar HTML must be text")
    if not isinstance(fetched_at, str) or not fetched_at:
        raise FOMCParseError("fetched_at is required")
    selected_years = _normalize_years(years=years, year=year)
    selected_months = _normalize_months(months=months, month=month)
    selected_start = _normalize_date_filter(start_date, field_name="start_date")
    selected_end = _normalize_date_filter(end_date, field_name="end_date")
    if selected_start and selected_end and selected_start > selected_end:
        raise FOMCParseError("start_date cannot be after end_date")

    html_parser = _FOMCHTMLParser()
    html_parser.feed(html_text)
    html_parser.close()
    items: list[RawNewsItem] = []
    for meeting in sorted(html_parser.meetings, key=lambda value: (value.start_date, value.end_date)):
        if not _meeting_matches_filters(
            meeting,
            years=selected_years,
            months=selected_months,
            start_date=selected_start,
            end_date=selected_end,
        ):
            continue
        items.append(_meeting_to_item(meeting=meeting, fetched_at=fetched_at, source_url=source_url))
    return items


def parse_fomc_calendar(
    html_text: str,
    *,
    fetched_at: str,
    source_url: str = FOMC_CALENDAR_URL,
    years: Iterable[int] | None = None,
    year: int | None = None,
    months: Iterable[int | str] | None = None,
    month: int | str | None = None,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
) -> list[RawNewsItem]:
    """Alias for :func:`parse_fomc_calendar_html`."""

    return parse_fomc_calendar_html(
        html_text,
        fetched_at=fetched_at,
        source_url=source_url,
        years=years,
        year=year,
        months=months,
        month=month,
        start_date=start_date,
        end_date=end_date,
    )


def _meeting_to_item(*, meeting: _FOMCMeeting, fetched_at: str, source_url: str) -> RawNewsItem:
    date_text = meeting.date_text
    title = f"FOMC Meeting: {meeting.month_label} {date_text}, {meeting.year}"
    meeting_range = _meeting_range_text(meeting)
    summary = f"Scheduled Federal Open Market Committee meeting: {meeting_range}."
    if meeting.is_sep:
        summary += " Meeting associated with a Summary of Economic Projections (SEP)."
    if meeting.note:
        summary += f" Note: {meeting.note}."
    domain = urlparse(source_url).netloc.lower().removeprefix("www.") or "federalreserve.gov"
    raw_payload = {
        "year": meeting.year,
        "month": meeting.month_label,
        "date_text": meeting.date_text,
        "start_date": meeting.start_date.isoformat(),
        "end_date": meeting.end_date.isoformat(),
        "is_sep": meeting.is_sep,
        "note": meeting.note,
        "links": list(meeting.links),
        "date_precision": "day",
        "time_status": "unavailable",
    }
    return RawNewsItem(
        source_key=FOMC_SOURCE_KEY,
        source_name=FOMC_SOURCE_NAME,
        source_type="official",
        feed_key=FOMC_FEED_KEY,
        title=title,
        url=source_url,
        domain=domain,
        published_at=meeting.start_date.isoformat(),
        fetched_at=fetched_at,
        summary=summary,
        source_country="US",
        source_language="en",
        event_type="fomc_meeting",
        verification_status="official_confirmed",
        duplicate_key=stable_news_item_id(source_key=FOMC_SOURCE_KEY, title=title, url=source_url),
        raw_payload=raw_payload,
    )


class _FOMCHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meetings: list[_FOMCMeeting] = []
        self._stack: list[str] = []
        self._heading_capture: tuple[int, list[str]] | None = None
        self._current_year: int | None = None
        self._current_meeting: dict[str, object] | None = None
        self._meeting_depth: int | None = None
        self._field_capture: tuple[str, int, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        depth = len(self._stack) + 1
        attrs_map = dict(attrs)
        classes = set((attrs_map.get("class") or "").split())
        if tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_capture = (depth, [])
        if tag.lower() == "div" and "fomc-meeting" in classes:
            if self._current_meeting is not None:
                self._finish_meeting()
            self._current_meeting = {"year": self._current_year, "links": []}
            self._meeting_depth = depth
        if self._current_meeting is not None and tag.lower() == "div":
            if "fomc-meeting__month" in classes:
                self._field_capture = ("month", depth, [])
            elif "fomc-meeting__date" in classes:
                self._field_capture = ("date", depth, [])
        if self._current_meeting is not None and tag.lower() == "a" and attrs_map.get("href"):
            links = self._current_meeting.setdefault("links", [])
            if isinstance(links, list):
                links.append(attrs_map["href"])
        self._stack.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        depth = len(self._stack)
        if self._heading_capture is not None and depth == self._heading_capture[0]:
            heading_text = _clean_text("".join(self._heading_capture[1]))
            match = _YEAR_HEADING.fullmatch(heading_text)
            if match:
                self._current_year = int(match.group("year"))
            self._heading_capture = None
        if self._field_capture is not None and depth == self._field_capture[1]:
            field_name, _field_depth, chunks = self._field_capture
            if self._current_meeting is not None:
                self._current_meeting[field_name] = _clean_text("".join(chunks))
            self._field_capture = None
        if self._meeting_depth == depth and tag == "div":
            self._finish_meeting()
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._heading_capture is not None:
            self._heading_capture[1].append(data)
        if self._field_capture is not None:
            self._field_capture[2].append(data)

    def _finish_meeting(self) -> None:
        meeting = self._current_meeting
        self._current_meeting = None
        self._meeting_depth = None
        if not meeting:
            return
        year = meeting.get("year")
        month_label = str(meeting.get("month") or "").strip()
        date_text = str(meeting.get("date") or "").strip()
        if not isinstance(year, int) or not month_label or not date_text:
            return
        parsed = _parse_meeting_dates(year=year, month_label=month_label, date_text=date_text)
        if parsed is None:
            return
        start, end, is_sep, note = parsed
        links_value = meeting.get("links")
        links = tuple(str(link) for link in links_value) if isinstance(links_value, list) else ()
        self.meetings.append(
            _FOMCMeeting(
                year=year,
                month_label=month_label,
                date_text=date_text,
                start_date=start,
                end_date=end,
                is_sep=is_sep,
                note=note,
                links=links,
            )
        )


def _parse_meeting_dates(
    *,
    year: int,
    month_label: str,
    date_text: str,
) -> tuple[date, date, bool, str | None] | None:
    normalized = _clean_text(date_text)
    is_sep = normalized.endswith("*")
    without_marker = normalized.rstrip("*").strip()
    match = _DATE_RANGE.fullmatch(without_marker)
    if match is None:
        return None
    start_day = int(match.group("start"))
    end_day = int(match.group("end") or match.group("start"))
    note = match.group("note").strip(" ,;:-") or None
    month_numbers = _parse_month_label(month_label)
    if not month_numbers:
        return None
    start_month = month_numbers[0]
    end_month = month_numbers[-1] if len(month_numbers) > 1 and match.group("end") else start_month
    end_year = year + 1 if end_month < start_month else year
    try:
        start_date = date(year, start_month, start_day)
        end_date = date(end_year, end_month, end_day)
    except ValueError:
        return None
    if end_date < start_date:
        return None
    return start_date, end_date, is_sep, note


def _parse_month_label(value: str) -> tuple[int, ...]:
    months: list[int] = []
    for token in re.split(r"\s*/\s*", value.strip()):
        month_number = _MONTHS.get(token.lower())
        if month_number is None:
            return ()
        months.append(month_number)
    return tuple(months)


def _meeting_matches_filters(
    meeting: _FOMCMeeting,
    *,
    years: set[int] | None,
    months: set[int] | None,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    if years is not None and not ({meeting.start_date.year, meeting.end_date.year} & years):
        return False
    if months is not None and not (_months_in_range(meeting.start_date, meeting.end_date) & months):
        return False
    if start_date is not None and meeting.end_date < start_date:
        return False
    if end_date is not None and meeting.start_date > end_date:
        return False
    return True


def _months_in_range(start_date: date, end_date: date) -> set[int]:
    months: set[int] = set()
    cursor = start_date.replace(day=1)
    end_cursor = end_date.replace(day=1)
    while cursor <= end_cursor:
        months.add(cursor.month)
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return months


def _normalize_years(*, years: Iterable[int] | None, year: int | None) -> set[int] | None:
    values = set(years or ())
    if year is not None:
        values.add(year)
    if not values:
        return None
    if any(isinstance(value, bool) or not isinstance(value, int) or not 1900 <= value <= 2100 for value in values):
        raise FOMCParseError("FOMC year filters must contain four-digit integers")
    return values


def _normalize_months(*, months: Iterable[int | str] | None, month: int | str | None) -> set[int] | None:
    values = list(months or ())
    if month is not None:
        values.append(month)
    if not values:
        return None
    result: set[int] = set()
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            month_number = value
        else:
            month_number = _MONTHS.get(str(value).strip().lower())
        if not isinstance(month_number, int) or not 1 <= month_number <= 12:
            raise FOMCParseError(f"Invalid FOMC month filter: {value!r}")
        result.add(month_number)
    return result


def _normalize_date_filter(value: str | date | None, *, field_name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise FOMCParseError(f"{field_name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise FOMCParseError(f"{field_name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise FOMCParseError(f"{field_name} must be YYYY-MM-DD")
    return parsed


def _meeting_range_text(meeting: _FOMCMeeting) -> str:
    if meeting.start_date == meeting.end_date:
        return meeting.start_date.isoformat()
    return f"{meeting.start_date.isoformat()} to {meeting.end_date.isoformat()}"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
