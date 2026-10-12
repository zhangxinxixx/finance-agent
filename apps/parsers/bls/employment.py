"""Normalize monthly Employment data returned by the BLS public API.

The BLS API returns observation periods (``M01`` through ``M12``), rather
than ISO dates.  This parser turns those periods into sortable calendar
months and deliberately leaves publication and revision metadata untouched:
the public response does not provide a release date or a verified vintage.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo


class BLSParseError(ValueError):
    """Raised when a BLS response cannot be interpreted safely."""


class BLSReleaseParseError(BLSParseError):
    """Raised when an Employment Situation release cannot be verified."""


BLS_EMPLOYMENT_RELEASE_CONTEXT_SYMBOL = "BLS_EMPLOYMENT_RELEASE"
BLS_EMPLOYMENT_RELEASE_SOURCE = "bls_employment_situation"
_RELEASE_TIMEZONE = "America/New_York"
_RELEASE_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_RELEASE_MONTH_NUMBERS = {name.lower(): index for index, name in enumerate(_RELEASE_MONTH_NAMES, start=1)}


@dataclass(frozen=True)
class BLSSeriesSpec:
    """Stable metadata for one BLS Employment series."""

    series_id: str
    label: str
    unit: str
    kind: str


BLS_SERIES_SPECS: tuple[BLSSeriesSpec, ...] = (
    BLSSeriesSpec(
        series_id="CES0000000001",
        label="总就业水平",
        unit="thousand_persons",
        kind="employment_level",
    ),
    BLSSeriesSpec(
        series_id="CES0500000003",
        label="平均时薪",
        unit="USD_per_hour",
        kind="hourly_earnings",
    ),
    BLSSeriesSpec(
        series_id="LNS14000000",
        label="失业率",
        unit="percent",
        kind="unemployment_rate",
    ),
    BLSSeriesSpec(
        series_id="LNS11300000",
        label="劳动参与率",
        unit="percent",
        kind="labor_force_participation_rate",
    ),
)
# The four headline/labour-market series are kept as the compatibility
# contract used by the original Employment parser.  Industry levels are
# registered separately so callers can opt into the bounded sector domain
# without changing the shape of ``parse_bls_employment_payload``.
BLS_INDUSTRY_SERIES_SPECS: tuple[BLSSeriesSpec, ...] = (
    BLSSeriesSpec(
        series_id="CES3000000001",
        label="制造业就业",
        unit="thousand_persons",
        kind="industry_employment_level",
    ),
    BLSSeriesSpec(
        series_id="CES5000000001",
        label="信息业就业",
        unit="thousand_persons",
        kind="industry_employment_level",
    ),
    BLSSeriesSpec(
        series_id="CES7072200001",
        label="餐饮服务业就业",
        unit="thousand_persons",
        kind="industry_employment_level",
    ),
    BLSSeriesSpec(
        series_id="CES9093161101",
        label="地方政府教育就业",
        unit="thousand_persons",
        kind="industry_employment_level",
    ),
    BLSSeriesSpec(
        series_id="CES6562000101",
        label="医疗保健就业",
        unit="thousand_persons",
        kind="industry_employment_level",
    ),
)
BLS_EMPLOYMENT_SERIES: tuple[str, ...] = tuple(spec.series_id for spec in BLS_SERIES_SPECS)
BLS_INDUSTRY_SERIES: tuple[str, ...] = tuple(spec.series_id for spec in BLS_INDUSTRY_SERIES_SPECS)
BLS_ALL_SERIES_SPECS: tuple[BLSSeriesSpec, ...] = BLS_SERIES_SPECS + BLS_INDUSTRY_SERIES_SPECS
BLS_ALL_SERIES: tuple[str, ...] = BLS_EMPLOYMENT_SERIES + BLS_INDUSTRY_SERIES
BLS_SERIES_BY_ID: dict[str, BLSSeriesSpec] = {
    spec.series_id: spec for spec in BLS_ALL_SERIES_SPECS
}
# Short alias retained for callers that use the naming convention of the
# existing FRED collector.
BLS_SERIES = BLS_EMPLOYMENT_SERIES

_MONTH_BY_PERIOD = {f"M{month:02d}": month for month in range(1, 13)}
_MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class BLSMonthlyObservation:
    """One normalized monthly observation from a BLS series."""

    series_id: str
    observation_month: str
    value: float
    period_name: str
    latest: bool
    footnote_codes: tuple[str, ...] = ()

    @property
    def point_date(self) -> str:
        """Return the first day of the observation month for ``MacroPoint``."""

        return f"{self.observation_month}-01"

    @property
    def month(self) -> str:
        """Compatibility alias for callers that call the field ``month``."""

        return self.observation_month

    def to_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "observation_month": self.observation_month,
            "value": self.value,
            "period_name": self.period_name,
            "latest": self.latest,
            "footnote_codes": list(self.footnote_codes),
            "point_date": self.point_date,
        }


@dataclass(frozen=True)
class BLSReleaseRevision:
    """One explicitly reported revision in an Employment Situation release."""

    observation_month: str
    previous_value_thousands: float
    revised_value_thousands: float
    delta_thousands: float
    direction: str
    evidence_excerpt: str

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_month": self.observation_month,
            "previous_value_thousands": self.previous_value_thousands,
            "revised_value_thousands": self.revised_value_thousands,
            "delta_thousands": self.delta_thousands,
            "direction": self.direction,
            "evidence_excerpt": self.evidence_excerpt,
        }


@dataclass(frozen=True)
class BLSSectorContribution:
    """One industry contribution explicitly stated by the release."""

    sector: str
    observation_month: str
    change_thousands: float
    direction: str
    evidence_excerpt: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sector": self.sector,
            "observation_month": self.observation_month,
            "change_thousands": self.change_thousands,
            "direction": self.direction,
            "evidence_excerpt": self.evidence_excerpt,
        }


@dataclass(frozen=True)
class BLSEmploymentRelease:
    """Verified publication context and facts from one official release."""

    status: str
    release_date: str | None
    release_time_local: str | None
    release_timezone: str | None
    release_datetime: str | None
    observation_month: str | None
    headline_new_jobs_thousands: float | None
    headline_unemployment_rate: float | None
    headline_wage_mom_pct: float | None
    headline_wage_yoy_pct: float | None
    revisions: tuple[BLSReleaseRevision, ...] = ()
    sector_contributions: tuple[BLSSectorContribution, ...] = ()
    missing_fields: tuple[str, ...] = ()
    parser_notes: tuple[str, ...] = ()
    evidence_excerpts: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "release_date": self.release_date,
            "release_time_local": self.release_time_local,
            "release_timezone": self.release_timezone,
            "release_datetime": self.release_datetime,
            "observation_month": self.observation_month,
            "headline": {
                "new_jobs_thousands": self.headline_new_jobs_thousands,
                "unemployment_rate": self.headline_unemployment_rate,
                "wage_mom_pct": self.headline_wage_mom_pct,
                "wage_yoy_pct": self.headline_wage_yoy_pct,
            },
            "revisions": [item.to_dict() for item in self.revisions],
            "sector_contributions": [item.to_dict() for item in self.sector_contributions],
            "missing_fields": list(self.missing_fields),
            "parser_notes": list(self.parser_notes),
            "evidence_excerpts": self.evidence_excerpts,
        }


class _ReleaseTextExtractor(HTMLParser):
    """Extract readable release text while ignoring script and style blocks."""

    _BLOCK_TAGS = frozenset({"br", "div", "h1", "h2", "h3", "li", "p", "pre", "td", "th", "tr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth == 0 and normalized in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth == 0 and normalized in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def parse_bls_employment_release_html(
    payload: str | bytes,
    *,
    expected_release_date: str | None = None,
    expected_observation_month: str | None = None,
) -> BLSEmploymentRelease:
    """Parse and validate an official Employment Situation HTML release.

    The release page is the only source for publication time, explicit
    revisions, and industry contributions.  This parser never reconstructs
    a prior vintage from the current BLS API series.
    """

    if isinstance(payload, bytes):
        try:
            html = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BLSReleaseParseError("Employment release is not valid UTF-8") from exc
    elif isinstance(payload, str):
        html = payload
    else:
        raise BLSReleaseParseError("Employment release payload must be text or bytes")
    if not html.strip():
        raise BLSReleaseParseError("Employment release payload is empty")

    extractor = _ReleaseTextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
    except (ValueError, TypeError) as exc:
        raise BLSReleaseParseError(f"Employment release HTML parse failed: {exc}") from exc
    text = _normalize_release_text("".join(extractor.parts))
    release_date, release_time_local, release_datetime, publication_excerpt = _parse_release_timestamp(text)
    observation_month = _parse_release_observation_month(text)
    if expected_release_date and release_date != expected_release_date:
        raise BLSReleaseParseError(
            f"Employment release date mismatch: expected {expected_release_date}, got {release_date or 'unavailable'}"
        )
    if expected_observation_month and observation_month != expected_observation_month:
        raise BLSReleaseParseError(
            "Employment release observation month mismatch: "
            f"expected {expected_observation_month}, got {observation_month or 'unavailable'}"
        )

    headline_new_jobs = _parse_headline_new_jobs(text)
    unemployment_rate = _parse_headline_unemployment_rate(text)
    wage_mom = _parse_headline_wage_mom(text)
    wage_yoy = _parse_headline_wage_yoy(text)
    revisions = _parse_release_revisions(text, observation_month)
    sectors = _parse_sector_contributions(text, observation_month)
    headline_excerpt = _first_sentence_matching(text, r"Total\s+nonfarm\s+payroll\s+employment")
    wages_excerpt = _first_sentence_matching(text, r"average\s+hourly\s+earnings")

    missing: list[str] = []
    if release_date is None:
        missing.append("release_date")
    if observation_month is None:
        missing.append("observation_month")
    if headline_new_jobs is None:
        missing.append("headline.new_jobs_thousands")
    if unemployment_rate is None:
        missing.append("headline.unemployment_rate")
    if wage_mom is None:
        missing.append("headline.wage_mom_pct")
    if wage_yoy is None:
        missing.append("headline.wage_yoy_pct")
    if not revisions:
        missing.append("revisions")
    if not sectors:
        missing.append("sector_contributions")
    required_missing = {"release_date", "observation_month", "headline.new_jobs_thousands"}
    status = "unavailable" if required_missing.intersection(missing) else ("partial" if missing else "available")
    return BLSEmploymentRelease(
        status=status,
        release_date=release_date,
        release_time_local=release_time_local,
        release_timezone=_RELEASE_TIMEZONE if release_time_local else None,
        release_datetime=release_datetime,
        observation_month=observation_month,
        headline_new_jobs_thousands=headline_new_jobs,
        headline_unemployment_rate=unemployment_rate,
        headline_wage_mom_pct=wage_mom,
        headline_wage_yoy_pct=wage_yoy,
        revisions=tuple(revisions),
        sector_contributions=tuple(sectors),
        missing_fields=tuple(missing),
        evidence_excerpts={
            "publication": publication_excerpt,
            "headline": headline_excerpt,
            "wages": wages_excerpt,
            "revisions": [item.evidence_excerpt for item in revisions],
            "sector_contributions": [item.evidence_excerpt for item in sectors],
        },
    )


def _normalize_release_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _parse_release_timestamp(text: str) -> tuple[str | None, str | None, str | None, str | None]:
    match = re.search(
        r"(?P<time>\d{1,2}:\d{2}\s*[ap]\.m\.?)\s*\(ET\)\s*(?:[A-Za-z]+,\s*)?"
        r"(?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None, None, None, None
    try:
        release_day = datetime.strptime(match.group("date"), "%B %d, %Y").date()
        local_time = datetime.strptime(
            re.sub(r"\s+", " ", match.group("time").replace("a.m.", "AM").replace("p.m.", "PM")),
            "%I:%M %p",
        ).time()
    except ValueError as exc:
        raise BLSReleaseParseError(f"Invalid Employment release timestamp: {match.group(0)!r}") from exc
    aware = datetime.combine(release_day, local_time, tzinfo=ZoneInfo(_RELEASE_TIMEZONE))
    return release_day.isoformat(), local_time.strftime("%H:%M"), aware.isoformat(), match.group(0)


def _parse_release_observation_month(text: str) -> str | None:
    match = re.search(
        r"THE\s+EMPLOYMENT\s+SITUATION\s*[-–—:]\s*"
        r"(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    month_number = _RELEASE_MONTH_NUMBERS.get(match.group("month").lower())
    return f"{match.group('year')}-{month_number:02d}" if month_number else None


def _parse_headline_new_jobs(text: str) -> float | None:
    match = re.search(
        r"Total\s+nonfarm\s+payroll\s+employment\s+"
        r"(?P<verb>increased|rose|grew|decreased|fell|declined)\s+by\s+"
        r"(?P<value>[+-]?\d[\d,]*)\s+in\s+",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    magnitude = _parse_number(match.group("value")) / 1000.0
    return _signed_by_direction(magnitude, match.group("verb"))


def _parse_headline_unemployment_rate(text: str) -> float | None:
    match = re.search(
        r"unemployment\s+rate\s+(?:was\s+unchanged\s+at|(?:rose|increased|fell|declined|decreased)\s+to|is\s+)"
        r"\s*(?P<value>\d+(?:\.\d+)?)\s+percent",
        text,
        flags=re.IGNORECASE,
    )
    return float(match.group("value")) if match else None


def _parse_headline_wage_mom(text: str) -> float | None:
    match = re.search(
        r"average\s+hourly\s+earnings.*?\bor\s+(?P<value>[+-]?\d+(?:\.\d+)?)\s+percent",
        text,
        flags=re.IGNORECASE,
    )
    return float(match.group("value")) if match else None


def _parse_headline_wage_yoy(text: str) -> float | None:
    match = re.search(
        r"Over\s+the\s+year,\s+average\s+hourly\s+earnings.*?"
        r"(?:increased|rose|grew|decreased|fell|declined)\s+by\s+"
        r"(?P<value>[+-]?\d+(?:\.\d+)?)\s+percent",
        text,
        flags=re.IGNORECASE,
    )
    return float(match.group("value")) if match else None


def _parse_release_revisions(text: str, observation_month: str | None) -> list[BLSReleaseRevision]:
    if observation_month is None:
        return []
    year = int(observation_month[:4])
    match_pattern = re.compile(
        r"(?:change\s+in\s+total\s+nonfarm\s+payroll\s+employment|the\s+change)\s+for\s+"
        r"(?P<month>[A-Za-z]+)(?:\s+(?P<year>\d{4}))?\s+was\s+revised\s+"
        r"(?P<direction>up|down)\s+by\s+(?P<reported>[+-]?\d[\d,]*)\s*,?\s*"
        r"from\s+(?P<previous>[+-]?\d[\d,]*)\s+to\s+(?P<revised>[+-]?\d[\d,]*)",
        flags=re.IGNORECASE,
    )
    revisions: list[BLSReleaseRevision] = []
    for match in match_pattern.finditer(text):
        month_number = _RELEASE_MONTH_NUMBERS.get(match.group("month").lower())
        if month_number is None:
            continue
        revision_year = int(match.group("year") or year)
        previous = _parse_number(match.group("previous")) / 1000.0
        revised = _parse_number(match.group("revised")) / 1000.0
        revisions.append(
            BLSReleaseRevision(
                observation_month=f"{revision_year:04d}-{month_number:02d}",
                previous_value_thousands=previous,
                revised_value_thousands=revised,
                delta_thousands=round(revised - previous, 6),
                direction=match.group("direction").lower(),
                evidence_excerpt=match.group(0),
            )
        )
    return revisions


def _parse_sector_contributions(text: str, observation_month: str | None) -> list[BLSSectorContribution]:
    if observation_month is None:
        return []
    month_name = _RELEASE_MONTH_NAMES[int(observation_month[5:7]) - 1]
    patterns = (
        re.compile(
            r"employment\s+in\s+(?P<sector>[A-Za-z][A-Za-z0-9 &'/-]+?)\s+"
            r"(?P<verb>increased|rose|grew|declined|decreased|fell)\s+by\s+"
            r"(?P<value>[+-]?\d[\d,]*)\s+in\s+(?P<month>[A-Za-z]+)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?P<sector>[A-Za-z][A-Za-z0-9 &'/-]+?)\s+(?P<verb>added|lost)\s+"
            r"(?P<value>[+-]?\d[\d,]*)\s+jobs\s+in\s+(?P<month>[A-Za-z]+)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?P<sector>[A-Za-z][A-Za-z0-9 &'/-]+?)\s+employment\s+"
            r"(?P<verb>increased|rose|grew|declined|decreased|fell)\s+by\s+"
            r"(?P<value>[+-]?\d[\d,]*)\s+in\s+(?P<month>[A-Za-z]+)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"employment\s+in\s+(?P<sector>[A-Za-z][A-Za-z0-9 &'/-]+?)\s+"
            r"[^.;]{0,100}?\((?P<value>[+-]\d[\d,]*)\)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"(?P<sector>[A-Za-z][A-Za-z0-9 &'/-]+?)\s+employment\s+"
            r"[^.;]{0,100}?\((?P<value>[+-]\d[\d,]*)\)",
            flags=re.IGNORECASE,
        ),
    )
    contributions: list[BLSSectorContribution] = []
    seen: set[tuple[str, str]] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            month = match.groupdict().get("month")
            if month is not None and month.lower() != month_name.lower():
                continue
            sector = _clean_sector_name(match.group("sector"))
            if not sector:
                continue
            sector_lower = sector.lower()
            if (
                sector_lower in {"total nonfarm payroll", "total private"}
                or "employment situation" in sector_lower
                or "total nonfarm" in sector_lower
            ):
                continue
            value = _parse_number(match.group("value")) / 1000.0
            verb = match.group("verb").lower() if match.groupdict().get("verb") else ""
            change = _signed_by_direction(value, verb)
            key = (sector.lower(), observation_month)
            if key in seen:
                continue
            seen.add(key)
            contributions.append(
                BLSSectorContribution(
                    sector=sector,
                    observation_month=observation_month,
                    change_thousands=round(change, 6),
                    direction="increase" if change > 0 else "decrease" if change < 0 else "unchanged",
                    evidence_excerpt=match.group(0),
                )
            )
    return contributions


def _first_sentence_matching(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        return None
    start = match.start()
    remainder = text[match.end() :]
    end_match = re.search(r"\.\s+(?=[A-Z])", remainder)
    end = match.end() + end_match.start() + 1 if end_match else min(len(text), match.end() + 600)
    return text[start:end].strip()


def _clean_sector_name(value: str) -> str:
    sector = " ".join(value.split()).strip(" ,;:")
    sector = re.sub(r"^(?:in\s+)?(?:the\s+)?", "", sector, flags=re.IGNORECASE)
    sector = re.sub(r"\s+(?:continued|has|was|were|is)\s+.*$", "", sector, flags=re.IGNORECASE)
    return sector.strip(" ,;:")


def _parse_number(value: str) -> float:
    try:
        return float(value.replace(",", "").replace("−", "-"))
    except (TypeError, ValueError) as exc:
        raise BLSReleaseParseError(f"Invalid numeric release value: {value!r}") from exc


def _signed_by_direction(value: float, direction: str) -> float:
    if direction.lower() in {"decreased", "fell", "declined", "lost", "down"}:
        return -abs(value)
    return abs(value)


def normalize_bls_cutoff_month(cutoff_month: str | None) -> str | None:
    """Validate and normalize ``YYYY-MM`` or an ISO date to ``YYYY-MM``."""

    if cutoff_month is None:
        return None
    value = str(cutoff_month).strip()
    if len(value) == 10:
        if not _is_iso_date(value):
            raise BLSParseError(f"Invalid BLS cutoff date: {cutoff_month!r}")
        value = value[:7]
    if _MONTH_PATTERN.fullmatch(value) is None:
        raise BLSParseError(f"Invalid BLS cutoff month: {cutoff_month!r}")
    return value


def parse_bls_series_payload(
    payload: Mapping[str, object],
    *,
    series_id: str,
    cutoff_month: str | None = None,
) -> list[BLSMonthlyObservation]:
    """Parse one requested series from a BLS API response.

    Missing values, annual ``M13`` rows, and rows after ``cutoff_month`` are
    omitted.  An explicit API failure or malformed response raises a typed
    error so a collector can mark just this series unavailable.
    """

    if not isinstance(payload, Mapping):
        raise BLSParseError("BLS payload must be a mapping")

    status = payload.get("status")
    if status not in (None, "", "REQUEST_SUCCEEDED"):
        message = _first_message(payload.get("message"))
        suffix = f": {message}" if message else ""
        raise BLSParseError(f"BLS API returned status {status!r}{suffix}")

    results = payload.get("Results")
    if not isinstance(results, Mapping):
        raise BLSParseError("BLS payload is missing Results")
    series_rows = results.get("series")
    if not isinstance(series_rows, list):
        raise BLSParseError("BLS payload is missing Results.series")

    normalized_cutoff = normalize_bls_cutoff_month(cutoff_month)
    matching_series = next(
        (item for item in series_rows if isinstance(item, Mapping) and str(item.get("seriesID") or "") == series_id),
        None,
    )
    if matching_series is None:
        return []

    data_rows = matching_series.get("data")
    if not isinstance(data_rows, list):
        raise BLSParseError(f"BLS series {series_id} is missing data")

    observations_by_month: dict[str, BLSMonthlyObservation] = {}
    for row in data_rows:
        if not isinstance(row, Mapping):
            raise BLSParseError(f"BLS series {series_id} contains a non-object data row")
        period = str(row.get("period") or "").upper()
        month_number = _MONTH_BY_PERIOD.get(period)
        if month_number is None:
            # M13 is an annual average and all other non-month periods are
            # outside the monthly Employment contract.
            continue

        year_value = str(row.get("year") or "")
        if not year_value.isdigit() or len(year_value) != 4:
            raise BLSParseError(f"Invalid BLS year for {series_id}: {year_value!r}")
        observation_month = f"{year_value}-{month_number:02d}"
        if normalized_cutoff is not None and observation_month > normalized_cutoff:
            continue

        numeric_value = _coerce_numeric(row.get("value"))
        if numeric_value is None:
            continue
        footnote_codes = _footnote_codes(row.get("footnotes"))
        observation = BLSMonthlyObservation(
            series_id=series_id,
            observation_month=observation_month,
            value=numeric_value,
            period_name=str(row.get("periodName") or _MONTH_NAMES[month_number]),
            latest=_coerce_bool(row.get("latest")),
            footnote_codes=footnote_codes,
        )
        previous = observations_by_month.get(observation_month)
        if previous is not None and previous != observation:
            raise BLSParseError(f"Conflicting duplicate BLS observation for {series_id} {observation_month}")
        observations_by_month[observation_month] = observation

    return [observations_by_month[month] for month in sorted(observations_by_month)]


def parse_bls_employment_payload(
    payload: Mapping[str, object],
    *,
    cutoff_month: str | None = None,
) -> dict[str, list[BLSMonthlyObservation]]:
    """Parse all four Employment series in a BLS response."""

    return {
        series_id: parse_bls_series_payload(payload, series_id=series_id, cutoff_month=cutoff_month)
        for series_id in BLS_EMPLOYMENT_SERIES
    }


def parse_bls_industry_payload(
    payload: Mapping[str, object],
    *,
    cutoff_month: str | None = None,
) -> dict[str, list[BLSMonthlyObservation]]:
    """Parse the bounded industry subset without changing the four-series API."""

    return {
        series_id: parse_bls_series_payload(payload, series_id=series_id, cutoff_month=cutoff_month)
        for series_id in BLS_INDUSTRY_SERIES
    }


def parse_bls_payload(
    payload: Mapping[str, object],
    *,
    cutoff_month: str | None = None,
) -> dict[str, list[BLSMonthlyObservation]]:
    """Alias for :func:`parse_bls_employment_payload`."""

    return parse_bls_employment_payload(payload, cutoff_month=cutoff_month)


def _coerce_numeric(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip() in {"", ".", "-", "—"}:
        return None
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    return numeric_value if math.isfinite(numeric_value) else None


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _footnote_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    codes: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("code") or "").strip()
        if code:
            codes.append(code)
    return tuple(codes)


def _first_message(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            message = str(item).strip()
            if message:
                return message
    if value not in (None, ""):
        return str(value).strip() or None
    return None


def _is_iso_date(value: str) -> bool:
    year_month_day = value.split("-")
    if len(year_month_day) != 3 or any(not part.isdigit() for part in year_month_day):
        return False
    year, month, day = (int(part) for part in year_month_day)
    if len(year_month_day[0]) != 4 or len(year_month_day[1]) != 2 or len(year_month_day[2]) != 2:
        return False
    if not 1 <= month <= 12:
        return False
    days_in_month = 29 if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 31
    if month in {4, 6, 9, 11}:
        days_in_month = 30
    elif month == 2:
        days_in_month = 28
    return 1 <= day <= days_in_month
