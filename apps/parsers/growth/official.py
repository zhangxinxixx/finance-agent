"""Pure parsers for official Atlanta Fed GDPNow and ISM report pages.

The source pages use different calendars and different meanings of "date".
This module keeps those meanings explicit: GDPNow's observation date is the
provider's update date, while an ISM page is normalized to the first day of
its survey reference month and carries ``date_semantics`` metadata.  Release
times are used only when the official page states them; no calendar date is
invented from a fixed weekday rule.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from html import unescape
from html.parser import HTMLParser
from typing import Any, Mapping
from zoneinfo import ZoneInfo


GDP_NOW_SOURCE_URL = "https://www.atlantafed.org/data/research-data"
GDP_NOW_COMMENTARY_URL = (
    "https://www.atlantafed.org/research-and-data/data/gdpnow/"
    "current-and-past-gdpnow-commentaries"
)
ISM_MANUFACTURING_SOURCE_URL_TEMPLATE = (
    "https://www.ismworld.org/supply-management-news-and-reports/reports/"
    "ism-pmi-reports/pmi/{period}/"
)
ISM_SERVICES_SOURCE_URL_TEMPLATE = (
    "https://www.ismworld.org/supply-management-news-and-reports/reports/"
    "ism-pmi-reports/services/{period}/"
)

GDP_NOW_SYMBOL = "GDP_NOW"
ISM_MANUFACTURING_SYMBOL = "ISM_MANUFACTURING"
ISM_SERVICES_SYMBOL = "ISM_SERVICES"
ISM_SERVICES_PRICES_SYMBOL = "ISM_SERVICES_PRICES"

# PR Newswire is used as an issuer-published transport fallback when the
# ISM report page is behind SSO/CAPTCHA or is temporarily unreachable.  It is
# intentionally kept separate from the ISM report-page URLs so the resulting
# source reference can state which transport was actually used.
ISM_PRNEWSWIRE_ISSUER_URL = "https://www.prnewswire.com/news/institute-for-supply-management/"
ISM_PRNEWSWIRE_BASE_URL = "https://www.prnewswire.com"

_MONTHS = (
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
_MONTH_NUMBERS = {name.lower(): index for index, name in enumerate(_MONTHS, start=1)}
_QUARTER_NUMBERS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
}
_ET = ZoneInfo("America/New_York")
_NUMBER = r"[-+]?\d+(?:\.\d+)?"


@dataclass(frozen=True)
class GrowthObservation:
    """One normalized official growth observation before ``MacroPoint``."""

    symbol: str
    value: float
    observation_date: str
    reference_period: str
    source: str
    source_url: str
    previous_value: float | None = None
    previous_reference_period: str | None = None
    release_date: str | None = None
    release_time: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GrowthSchedule:
    """Officially stated next-release metadata, when present."""

    expected_release_date: str | None = None
    expected_release_time: str | None = None
    expected_release_timezone: str | None = None
    previous_value: float | None = None
    previous_reference_period: str | None = None
    source_note: str | None = None


@dataclass(frozen=True)
class ISMReleaseCandidate:
    """A report link discovered in the ISM PR Newswire issuer feed."""

    url: str
    title: str
    reference_period: str
    listing_release_date: str | None = None


class _VisibleTextParser(HTMLParser):
    """Extract visible text without retaining the report body."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag.lower() in {
            "br", "div", "h1", "h2", "h3", "h4", "li", "p", "td", "th", "tr"
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "template"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and normalized in {
            "br", "div", "h1", "h2", "h3", "h4", "li", "p", "td", "th", "tr"
        }:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


class _AnchorTextParser(HTMLParser):
    """Collect anchor hrefs and their visible text from a release index."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1
            return
        if normalized == "a" and self._ignored_depth == 0 and self._href is None:
            attrs_map = dict(attrs)
            href = str(attrs_map.get("href") or "").strip()
            if href:
                self._href = href
                self._parts = []

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "template"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if normalized == "a" and self._href is not None and self._ignored_depth == 0:
            text = re.sub(r"\s+", " ", unescape("".join(self._parts))).strip()
            self.links.append((self._href, text))
            self._href = None
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None and self._ignored_depth == 0:
            self._parts.append(data)


def parse_ism_prnewswire_index(
    payload: str | bytes,
    *,
    report_kind: str,
    reference_period: str,
) -> ISMReleaseCandidate | None:
    """Find a matching ISM report in the issuer's PR Newswire feed.

    The listing is only a locator.  The returned link still has to pass
    :func:`parse_ism_prnewswire_release`, which validates the article's issuer,
    report period and release timestamp before it can become a data point.
    """

    if report_kind not in {"manufacturing", "services"}:
        raise ValueError(f"unsupported ISM report kind: {report_kind!r}")
    expected = _normalize_reference_period(reference_period)
    parser = _AnchorTextParser()
    body = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    parser.feed(body)
    parser.close()
    expected_year, expected_month = (int(part) for part in expected.split("-"))
    expected_month_name = _MONTHS[expected_month - 1]
    kind_marker = "manufacturing pmi" if report_kind == "manufacturing" else "services pmi"
    candidates: list[ISMReleaseCandidate] = []
    for href, title in parser.links:
        absolute = _absolute_url(href)
        lowered = f"{absolute} {title}".lower()
        if "/news-releases/" not in absolute.lower() or kind_marker not in lowered:
            continue
        if expected_month_name.lower() not in lowered or str(expected_year) not in lowered:
            continue
        period = _period_from_month_year(lowered)
        if period != expected:
            continue
        candidates.append(
            ISMReleaseCandidate(
                url=absolute,
                title=title,
                reference_period=period,
                listing_release_date=_parse_listing_release_date(title),
            )
        )
    if not candidates:
        return None
    # The issuer feed is newest-first.  Sorting by the listing timestamp keeps
    # the result deterministic if a release is duplicated in the HTML.
    return sorted(
        candidates,
        key=lambda candidate: (candidate.listing_release_date or "", candidate.url),
        reverse=True,
    )[0]


def parse_ism_prnewswire_release(
    payload: str | bytes,
    *,
    report_kind: str,
    source_url: str,
    expected_period: str | None = None,
) -> tuple[list[GrowthObservation], GrowthSchedule]:
    """Parse an ISM-issued PR Newswire release with issuer/date validation."""

    text = _visible_text(payload)
    issuer_header = re.search(
        r"News\s+provided\s+by\s+Institute\s+for\s+Supply\s+Management",
        text,
        re.IGNORECASE,
    )
    issuer_footer = re.search(
        r"SOURCE\s+Institute\s+for\s+Supply\s+Management",
        text,
        re.IGNORECASE,
    )
    if issuer_header is None or issuer_footer is None:
        raise ValueError("ISM PR Newswire issuer is not verified")

    period = _parse_period_heading(text)
    if period is None:
        raise ValueError("ISM PR Newswire report reference period is missing")
    actual_period = f"{period[1]:04d}-{period[0]:02d}"
    if expected_period is not None and actual_period != _normalize_reference_period(expected_period):
        raise ValueError("ISM PR Newswire report period does not match the requested period")

    release_date, release_time, release_timezone = _parse_prnewswire_release_timestamp(text)
    if release_date is None:
        raise ValueError("ISM PR Newswire release date is missing")

    records, schedule = parse_ism_report_html(
        payload,
        report_kind=report_kind,
        source_url=source_url,
    )
    enriched: list[GrowthObservation] = []
    for record in records:
        metadata = {
            **record.metadata,
            "distribution_channel": "prnewswire",
            "issuer": "Institute for Supply Management",
            "issuer_verified": True,
            "release_timezone": release_timezone,
            "release_date_source": "prnewswire_header",
        }
        enriched.append(
            GrowthObservation(
                **{
                    **asdict(record),
                    "source": "ism_prnewswire",
                    "source_url": source_url,
                    "release_date": release_date,
                    "release_time": release_time,
                    "metadata": metadata,
                }
            )
        )
    return enriched, schedule


def _visible_text(payload: str | bytes) -> str:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    parser = _VisibleTextParser()
    parser.feed(payload)
    parser.close()
    return re.sub(r"[ \t\f\r]+", " ", unescape("".join(parser.parts))).strip()


def _number(value: object) -> float | None:
    if value is None:
        return None
    match = re.search(_NUMBER, str(value).replace(",", ""))
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _absolute_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return f"{ISM_PRNEWSWIRE_BASE_URL}{href}"
    return f"{ISM_PRNEWSWIRE_BASE_URL}/{href}"


def _normalize_reference_period(value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%Y-%m")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid ISM reference period: {value!r}") from exc
    return parsed.strftime("%Y-%m")


def _period_from_month_year(value: str) -> str | None:
    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(20\d{2})",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return f"{int(match.group(2)):04d}-{_MONTH_NUMBERS[match.group(1).lower()]:02d}"


def _parse_listing_release_date(value: str) -> str | None:
    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s*(20\d{2})(?:,\s*(\d{1,2}:\d{2})\s*(a\.m\.|p\.m\.|ET))?",
        value,
        re.IGNORECASE,
    )
    if match is None:
        # The listing uses abbreviated month names (for example ``Sep``).
        match = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
            r"(\d{1,2}),\s*(20\d{2})(?:,\s*(\d{1,2}:\d{2})\s*(a\.m\.|p\.m\.|ET))?",
            value,
            re.IGNORECASE,
        )
    if match is None:
        return None
    month_text = match.group(1).lower()
    month = next((number for name, number in _MONTH_NUMBERS.items() if name.startswith(month_text)), None)
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2))).isoformat()
    except ValueError:
        return None


def _parse_prnewswire_release_timestamp(text: str) -> tuple[str | None, str | None, str | None]:
    match = re.search(
        r"News\s+provided\s+by\s+Institute\s+for\s+Supply\s+Management\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s*(20\d{2}),?\s*(\d{1,2}:\d{2})\s*ET",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        # PR Newswire's visible header currently uses abbreviated month names
        # in the listing/article metadata on some render paths.
        match = re.search(
            r"News\s+provided\s+by\s+Institute\s+for\s+Supply\s+Management\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
            r"(\d{1,2}),\s*(20\d{2}),?\s*(\d{1,2}:\d{2})\s*ET",
            text,
            re.IGNORECASE | re.DOTALL,
        )
    if match is None:
        return None, None, None
    month_text = match.group(1).lower()
    month = next((number for name, number in _MONTH_NUMBERS.items() if name.startswith(month_text)), None)
    if month is None:
        return None, None, None
    try:
        release_date = date(int(match.group(3)), month, int(match.group(2)))
        hour, minute = (int(value) for value in match.group(4).split(":"))
        local = datetime.combine(release_date, time(hour, minute), tzinfo=_ET)
    except (TypeError, ValueError):
        return None, None, None
    return release_date.isoformat(), local.isoformat(), "America/New_York"


def _iso_date(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            return None


def _period_from_gdp_name(name: str) -> str | None:
    match = re.search(r"(\d{4})\s*:\s*Q([1-4])", name, re.IGNORECASE)
    if match:
        return f"{match.group(1)}-Q{match.group(2)}"
    match = re.search(
        r"(first|second|third|fourth)\s+quarter\s+of\s+(\d{4})",
        name,
        re.IGNORECASE,
    )
    if match:
        return f"{match.group(2)}-Q{_QUARTER_NUMBERS[match.group(1).lower()]}"
    return None


def parse_gdpnow_payload(
    payload: Mapping[str, Any],
    *,
    source_url: str = GDP_NOW_SOURCE_URL,
) -> GrowthObservation:
    """Parse the Atlanta Fed's ``ResearchData`` JSON endpoint."""

    rows = payload.get("ResearchData")
    if not isinstance(rows, list):
        raise ValueError("Atlanta Fed GDPNow payload has no ResearchData list")

    candidate: Mapping[str, Any] | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("IconAlias") or "").lower() == "gdpnow" or "gdpnow" in str(row.get("Name") or "").lower():
            candidate = row
            break
    if candidate is None:
        raise ValueError("Atlanta Fed GDPNow observation is not published")

    value = _number(candidate.get("Indicator"))
    updated_date = _iso_date(candidate.get("UpdatedDate"))
    name = str(candidate.get("Name") or "")
    reference_period = _period_from_gdp_name(name)
    if value is None or updated_date is None or reference_period is None:
        raise ValueError("Atlanta Fed GDPNow observation is incomplete")

    previous_value = next(
        (
            _number(candidate.get(key))
            for key in ("PreviousIndicator", "PreviousValue", "PreviousEstimate")
            if _number(candidate.get(key)) is not None
        ),
        None,
    )
    return GrowthObservation(
        symbol=GDP_NOW_SYMBOL,
        value=value,
        observation_date=updated_date,
        reference_period=reference_period,
        source="atlanta_fed_gdpnow",
        source_url=source_url,
        previous_value=previous_value,
        metadata={
            "date_semantics": "provider_update_date",
            "unit": "% q/q saar",
            "name": name,
            "official_timestamp": candidate.get("UpdatedDate"),
        },
    )


def parse_gdpnow_commentary(
    payload: str | bytes,
    *,
    latest_observation_date: str | None = None,
) -> GrowthSchedule:
    """Read the next update date and previous estimate from official text."""

    text = _visible_text(payload)
    current_date = _parse_first_long_date(text)
    next_date_match = re.search(
        r"next\s+GDPNow\s+update(?:\s+is|\s+will\s+be(?:\s+on|\s+no\s+later\s+than)?)?\s+"
        r"(?:[A-Za-z]+,?\s+)?(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2})(?:,\s*(\d{4}))?",
        text,
        re.IGNORECASE,
    )
    expected_date = None
    if next_date_match:
        year = int(next_date_match.group(3) or (current_date or latest_observation_date or "0000")[:4])
        month = _MONTH_NUMBERS[next_date_match.group(1).lower()]
        day = int(next_date_match.group(2))
        try:
            candidate = date(year, month, day)
            if (current_date or latest_observation_date) and candidate.isoformat() < (current_date or latest_observation_date):
                candidate = date(year + 1, month, day)
            expected_date = candidate.isoformat()
        except ValueError:
            expected_date = None

    first_sentence = re.search(
        r"GDPNow\s+model\s+estimate.*?is\s+(%s)\s+percent.*?"
        r"(?:down\s+from|up\s+from|unchanged\s+from)\s+(%s)\s+percent" % (_NUMBER, _NUMBER),
        text,
        re.IGNORECASE | re.DOTALL,
    )
    previous_value = _number(first_sentence.group(2)) if first_sentence else None
    # Do not truncate at the first full stop: the estimate itself contains a
    # decimal (for example ``4.7 percent``), so doing so would discard the
    # quarter phrase before it.
    current_period = _period_from_gdp_name(text)
    previous_period = current_period
    return GrowthSchedule(
        expected_release_date=expected_date,
        expected_release_time=None,
        expected_release_timezone=None,
        previous_value=previous_value,
        previous_reference_period=previous_period,
        source_note="official commentary states next update date; time is not published",
    )


def _parse_first_long_date(text: str) -> str | None:
    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s*(\d{4})",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        return date(
            int(match.group(3)),
            _MONTH_NUMBERS[match.group(1).lower()],
            int(match.group(2)),
        ).isoformat()
    except ValueError:
        return None


def _parse_period_heading(text: str) -> tuple[int, int] | None:
    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{4})\s+ISM",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return _MONTH_NUMBERS[match.group(1).lower()], int(match.group(2))


def _next_ism_release(text: str, *, current_year: int) -> tuple[str | None, str | None, str | None]:
    match = re.search(
        r"next\s+ISM.*?Report.*?released\s+at\s+"
        r"(\d{1,2}:\d{2})\s*(a\.m\.|p\.m\.)\s+ET\s+on\s+"
        r"(?:[A-Za-z]+,?\s+)?(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s*(\d{4})",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None, None, None
    hour, minute = (int(part) for part in match.group(1).split(":"))
    if match.group(2).lower().startswith("p") and hour != 12:
        hour += 12
    if match.group(2).lower().startswith("a") and hour == 12:
        hour = 0
    try:
        release_date = date(
            int(match.group(5)),
            _MONTH_NUMBERS[match.group(3).lower()],
            int(match.group(4)),
        )
        local = datetime.combine(release_date, time(hour, minute), tzinfo=_ET)
    except ValueError:
        return None, None, None
    return local.date().isoformat(), local.isoformat(), "America/New_York"


def _previous_period(year: int, month: int) -> str:
    return f"{year - 1 if month == 1 else year:04d}-{12 if month == 1 else month - 1:02d}"


def parse_ism_report_html(
    payload: str | bytes,
    *,
    report_kind: str,
    source_url: str,
) -> tuple[list[GrowthObservation], GrowthSchedule]:
    """Parse current and prior values from an official ISM report page.

    ``report_kind`` must be ``manufacturing`` or ``services``.  The services
    page also provides the Prices Index, which is emitted as its own record.
    """

    if report_kind not in {"manufacturing", "services"}:
        raise ValueError(f"unsupported ISM report kind: {report_kind!r}")
    text = _visible_text(payload)
    period = _parse_period_heading(text)
    if period is None:
        raise ValueError("ISM report reference period is missing")
    month, year = period
    month_name = _MONTHS[month - 1]
    reference_period = f"{year:04d}-{month:02d}"
    observation_date = f"{reference_period}-01"
    prior_period = _previous_period(year, month)

    if report_kind == "manufacturing":
        value_match = re.search(
            rf"Manufacturing\s+PMI.*?registered\s+({_NUMBER})\s+percent\s+in\s+{month_name}",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        prior_match = re.search(
            rf"Manufacturing\s+PMI.*?(?:compared\s+to|below|above).*?figure\s+of\s+({_NUMBER})",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        symbol = ISM_MANUFACTURING_SYMBOL
        label = "ISM Manufacturing PMI"
        unit = "index"
    else:
        value_match = re.search(
            rf"Services\s+PMI.*?registered\s+({_NUMBER})\s+percent(?:\s+in\s+{month_name})?",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        prior_match = re.search(
            rf"Services\s+PMI.*?(?:compared\s+to|above|below).*?figure\s+of\s+({_NUMBER})",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        symbol = ISM_SERVICES_SYMBOL
        label = "ISM Services PMI"
        unit = "index"

    if value_match is None:
        raise ValueError(f"ISM {report_kind} PMI is not published")
    value = _number(value_match.group(1))
    previous_value = _number(prior_match.group(1)) if prior_match else None
    if value is None:
        raise ValueError(f"ISM {report_kind} PMI value is invalid")

    expected_date, expected_time, expected_timezone = _next_ism_release(text, current_year=year)
    schedule = GrowthSchedule(
        expected_release_date=expected_date,
        expected_release_time=expected_time,
        expected_release_timezone=expected_timezone,
        source_note="official ISM page states next release date and 10:00 a.m. ET",
    )
    common_metadata = {
        "date_semantics": "reference_period_start",
        "reference_period_kind": "month",
        "unit": unit,
        "release_date_status": "unavailable_on_page",
    }
    records = [
        GrowthObservation(
            symbol=symbol,
            value=value,
            observation_date=observation_date,
            reference_period=reference_period,
            source="ism_official",
            source_url=source_url,
            previous_value=previous_value,
            previous_reference_period=prior_period,
            metadata={**common_metadata, "label": label},
        )
    ]

    if report_kind == "services":
        price_match = re.search(
            rf"Prices\s+Index.*?(?:reading\s+of|registered\s+)\s*({_NUMBER})\s+percent\s+in\s+{month_name}",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if price_match is None:
            price_match = re.search(
                rf"Prices\s+Index.*?registered\s+({_NUMBER})\s+percent",
                text,
                re.IGNORECASE | re.DOTALL,
            )
        price_prior_match = re.search(
            r"Prices\s+Index.*?(?:compared\s+to|above|below).*?figure\s+of\s+"
            rf"({_NUMBER})",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if price_match is not None:
            price_value = _number(price_match.group(1))
            if price_value is None:
                raise ValueError("ISM services Prices Index value is invalid")
            records.append(
                GrowthObservation(
                    symbol=ISM_SERVICES_PRICES_SYMBOL,
                    value=price_value,
                    observation_date=observation_date,
                    reference_period=reference_period,
                    source="ism_official",
                    source_url=source_url,
                    previous_value=_number(price_prior_match.group(1)) if price_prior_match else None,
                    previous_reference_period=prior_period,
                    metadata={
                        **common_metadata,
                        "label": "ISM Services Prices Index",
                        "index_role": "inflation_input",
                    },
                )
            )
        else:
            schedule = GrowthSchedule(
                expected_release_date=expected_date,
                expected_release_time=expected_time,
                expected_release_timezone=expected_timezone,
                source_note="ISM Services page published but Prices Index was absent",
            )
    return records, schedule
