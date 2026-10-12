"""Official Treasury daily nominal and real yield curve collector."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import utc_now_iso

TREASURY_RATES_SOURCE = "treasury_rates"
# Keep a singular alias for callers that name a source constant after the
# collector rather than the pair of curves.
TREASURY_RATE_SOURCE = TREASURY_RATES_SOURCE
# Keep the original symbols first for stable downstream ordering, then expose
# the intermediate and long real-rate points used by the research passport.
# The Treasury CSV is the primary source for these points; FRED remains a
# separate fallback/history source and is not silently mixed into this
# same-date curve observation.
TREASURY_RATE_SYMBOLS = (
    "DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30",
    "DFII5", "DFII10", "DFII30",
)

TREASURY_DAILY_RATES_CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv"
)
TREASURY_NOMINAL_CURVE_TYPE = "daily_treasury_yield_curve"
TREASURY_REAL_CURVE_TYPE = "daily_treasury_real_yield_curve"

_NOMINAL_COLUMNS = {
    "DGS3MO": ("3 Mo", "3 MO", "3-month", "3 month", "3M"),
    "DGS2": ("2 Yr", "2 YR", "2-year", "2 year"),
    "DGS5": ("5 Yr", "5 YR", "5-year", "5 year"),
    "DGS10": ("10 Yr", "10 YR", "10-year", "10 year"),
    "DGS30": ("30 Yr", "30 YR", "30-year", "30 year"),
}
_REAL_COLUMNS = {
    "DFII5": ("5 YR", "5 Yr", "5-year", "5 year"),
    "DFII10": ("10 YR", "10 Yr", "10-year", "10 year"),
    "DFII30": ("30 YR", "30 Yr", "30-year", "30 year"),
}
_CURVE_BY_SYMBOL = {symbol: "nominal" for symbol in _NOMINAL_COLUMNS} | {
    symbol: "real" for symbol in _REAL_COLUMNS
}


def treasury_nominal_csv_url(year: int) -> str:
    """Return the official annual Treasury nominal curve CSV URL."""

    return _treasury_csv_url(year=year, curve_type=TREASURY_NOMINAL_CURVE_TYPE)


def treasury_real_csv_url(year: int) -> str:
    """Return the official annual Treasury real (TIPS) curve CSV URL."""

    return _treasury_csv_url(year=year, curve_type=TREASURY_REAL_CURVE_TYPE)


def collect_treasury_rate_curves(
    *,
    retrieved_date: str,
    storage_root: Path,
    symbols: tuple[str, ...] = TREASURY_RATE_SYMBOLS,
    client: Any | None = None,
    include_history: bool = False,
) -> CollectorResult:
    """Collect aligned Treasury nominal and real curve observations.

    The Treasury publishes nominal and real curves as separate annual CSVs.
    When both curves are requested, this collector chooses one latest common
    observation date on or before ``retrieved_date`` and only emits a point if
    every requested symbol is numeric on that date.  This prevents a current
    nominal observation from being silently paired with an older real yield.

    ``client`` is an optional injected HTTP client for tests.  An injected
    client remains owned by the caller; the internally-created client is
    closed by this function.  Values retain Treasury's published percentage
    point unit (for example, ``4.37`` means 4.37 percent).

    ``include_history=True`` emits all complete common dates in the inclusive
    62-calendar-day prior window, fetching the prior annual files when needed.
    Each failed CSV has one archived official TextView fallback. The internal
    client respects configured HTTP(S)/ALL_PROXY and NO_PROXY environment settings.
    """

    if not isinstance(include_history, bool):
        raise ValueError("include_history must be boolean")
    cutoff = _validate_retrieved_date(retrieved_date)
    requested_symbols = tuple(symbols)
    _validate_symbols(requested_symbols)
    if not requested_symbols:
        return CollectorResult(points=[], unavailable_symbols=[], source_refs=[])

    if client is not None:
        return _collect_with_client(
            client=client,
            cutoff=cutoff,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            requested_symbols=requested_symbols,
            include_history=include_history,
        )

    import httpx

    with httpx.Client(
        timeout=30.0,
        headers={"User-Agent": "finance-agent/0.1"},
        trust_env=True,
    ) as http_client:
        return _collect_with_client(
            client=http_client,
            cutoff=cutoff,
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            requested_symbols=requested_symbols,
            include_history=include_history,
        )


def treasury_textview_url(year: int, curve: str) -> str:
    if curve not in {"nominal", "real"}:
        raise ValueError("Treasury curve must be nominal or real")
    _validate_year(year)
    curve_type = TREASURY_NOMINAL_CURVE_TYPE if curve == "nominal" else TREASURY_REAL_CURVE_TYPE
    return (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView"
        f"?type={curve_type}&field_tdr_date_value={year}"
    )


def _collect_with_client(
    *, client: Any, cutoff: date, retrieved_date: str, storage_root: Path,
    requested_symbols: tuple[str, ...], include_history: bool = False,
) -> CollectorResult:
    # 62 calendar days include a prior monthly anchor plus weekends/holidays.
    # At most two annual files per curve, with one HTML fallback per failed file.
    start = cutoff - timedelta(days=62) if include_history else date(cutoff.year, 1, 1)
    retrieved_at = utc_now_iso()
    rows = {"nominal": {}, "real": {}}
    coordinates = {}
    sources = {}
    attempts = []
    errors = []
    for year in range(start.year, cutoff.year + 1):
        for curve in ("nominal", "real"):
            required = tuple(s for s in requested_symbols if _CURVE_BY_SYMBOL[s] == curve)
            csv_url = treasury_nominal_csv_url(year) if curve == "nominal" else treasury_real_csv_url(year)
            fallback_reason = None
            for fmt, url in (("csv", csv_url), ("html", treasury_textview_url(year, curve))):
                payload, raw_path, error = _fetch_and_archive(
                    client=client, url=url, storage_root=storage_root,
                    retrieved_date=retrieved_date, curve=curve, year=year, format=fmt,
                )
                parsed = None
                if error is None:
                    try:
                        parsed = (_parse_curve_csv(payload, required_symbols=required) if fmt == "csv"
                                  else _parse_curve_html(payload, required_symbols=required))
                        if not parsed or not any(
                            all(symbol in values for symbol in required) for values in parsed.values()
                        ):
                            raise ValueError("no complete numeric Treasury rows")
                    except Exception as exc:
                        error = f"Treasury {curve} {fmt} parse failed: {type(exc).__name__}: {exc}"
                attempt = {
                    # Retrieval evidence must not match a sourced MacroPoint.
                    "source": "treasury_rates_retrieval", "curve": curve, "source_url": url,
                    "source_format": fmt, "retrieved_at": retrieved_at,
                    "observation_cutoff_date": retrieved_date,
                    "status": "unavailable" if error else "available",
                }
                if raw_path:
                    attempt["raw_path"] = raw_path
                if error:
                    attempt["reason"] = error
                    attempts.append(attempt)
                    fallback_reason = error
                    if fmt == "html":
                        errors.append(error)
                    continue
                sources[curve] = (url, raw_path, fmt, fallback_reason)
                for day, values in parsed.items():
                    observed = date.fromisoformat(day)
                    if observed.year != year or not start <= observed <= cutoff:
                        continue
                    rows[curve][day] = values
                    coordinates[curve, day] = (url, raw_path, fmt, fallback_reason)
                break
    observations = []
    for day in sorted(set(rows["nominal"]) & set(rows["real"])):
        values = {s: rows[_CURVE_BY_SYMBOL[s]][day].get(s) for s in requested_symbols}
        if all(v is not None and math.isfinite(v) for v in values.values()):
            observations.append((day, values))
    if not observations:
        reason = "; ".join(errors) or f"No common complete Treasury curve observation on or before {retrieved_date}"
        refs = []
        for symbol in requested_symbols:
            curve = _CURVE_BY_SYMBOL[symbol]
            url, raw_path, fmt, _ = sources.get(curve, (
                treasury_textview_url(cutoff.year, curve), None, "html", None,
            ))
            ref = _source_ref(symbol=symbol, source_url=url, raw_path=raw_path,
                              retrieved_at=retrieved_at, retrieved_date=retrieved_date,
                              observation_date=None, status="unavailable", reason=reason)
            ref["source_format"] = fmt
            refs.append(ref)
        return CollectorResult([], list(requested_symbols), refs + attempts)
    if not include_history:
        observations = observations[-1:]
    points = []
    refs = []
    for day, values in observations:
        for symbol in requested_symbols:
            url, raw_path, fmt, fallback_reason = coordinates[_CURVE_BY_SYMBOL[symbol], day]
            points.append(MacroPoint(symbol=symbol, date=day, value=values[symbol],
                                     source=TREASURY_RATES_SOURCE, source_url=url,
                                     retrieved_at=retrieved_at, raw_path=raw_path))
            ref = _source_ref(symbol=symbol, source_url=url, raw_path=raw_path,
                              retrieved_at=retrieved_at, retrieved_date=retrieved_date,
                              observation_date=day, status="available")
            ref["source_format"] = fmt
            if fallback_reason:
                ref["fallback_reason"] = fallback_reason
            refs.append(ref)
    return CollectorResult(points=points, unavailable_symbols=[], source_refs=refs + attempts)


class _CurveTableParser(HTMLParser):
    """Extract table cells, preserving empty cells and rejecting shifted layouts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.invalid = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.table is not None:
                self.invalid = True
            self.table = []
        elif tag == "tr" and self.table is not None:
            if self.row is not None:
                self.invalid = True
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            if self.cell is not None:
                self.invalid = True
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.cell is not None:
                self.invalid = True
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            if self.row is not None:
                self.invalid = True
            self.tables.append(self.table)
            self.table = None


def _parse_curve_html(payload: bytes, *, required_symbols: tuple[str, ...]) -> dict[str, dict[str, float]]:
    parser = _CurveTableParser()
    parser.feed(payload.decode("utf-8-sig"))
    parser.close()
    if parser.invalid or parser.table is not None or parser.cell is not None:
        raise ValueError("malformed Treasury HTML table")
    candidates = []
    for table in parser.tables:
        for index, header in enumerate(table):
            normalized = [_normalize_header(cell) for cell in header]
            if "date" not in normalized:
                continue
            if not all(any(_normalize_header(alias) in normalized for alias in _aliases_for_symbol(s))
                       for s in required_symbols):
                continue
            data_rows = table[index + 1:]
            if any(len(row) != len(header) for row in data_rows):
                raise ValueError("missing or shifted Treasury HTML cells")
            if normalized.count("date") != 1:
                raise ValueError("ambiguous Treasury HTML date column")
            date_index = normalized.index("date")
            if any(_parse_treasury_date(row[date_index]) is None for row in data_rows):
                raise ValueError("malformed Treasury HTML observation date")
            # TextView includes inactive columns from other rate products.
            # Some share a tenor name with the active real curve (30 YR / 30 Yr).
            # Select the sole numeric column for each requested tenor, keeping
            # unrelated and entirely N/A columns out of DictReader's mapping.
            indices = []
            for symbol in required_symbols:
                aliases = {_normalize_header(alias) for alias in _aliases_for_symbol(symbol)}
                matching = [i for i, name in enumerate(normalized) if name in aliases]
                active = [i for i in matching if any(_parse_numeric(row[i]) is not None for row in data_rows)]
                if len(active) != 1:
                    raise ValueError(f"missing or ambiguous Treasury HTML column for {symbol}")
                indices.append(active[0])
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["Date", *[_aliases_for_symbol(s)[0] for s in required_symbols]])
            writer.writerows([[row[date_index], *[row[i] for i in indices]] for row in data_rows])
            candidates.append(_parse_curve_csv(buffer.getvalue().encode(), required_symbols=required_symbols))
            break
    if len(candidates) != 1:
        raise ValueError("missing or ambiguous Treasury HTML curve table")
    return candidates[0]


def _fetch_and_archive(
    *,
    client: Any,
    url: str,
    storage_root: Path,
    retrieved_date: str,
    curve: str,
    year: int,
    format: str = "csv",
) -> tuple[bytes | None, str | None, str | None]:
    try:
        response = client.get(url)
        response.raise_for_status()
        payload = bytes(response.content)
        if not payload:
            raise ValueError("empty response body")
        raw_path = _archive_raw_csv(
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            curve=curve,
            year=year,
            payload=payload,
            format=format,
        )
        return payload, raw_path, None
    except Exception as exc:
        return None, None, f"Treasury {curve} request/archive failed: {type(exc).__name__}: {exc}"


def _archive_raw_csv(
    *,
    storage_root: Path,
    retrieved_date: str,
    curve: str,
    year: int,
    payload: bytes,
    format: str = "csv",
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    relative_path = (
        Path("raw") / "macro" / "treasury_rates" / retrieved_date / f"{curve}-{year}-{timestamp}-{uuid4().hex[:12]}.{format}"
    )
    target = storage_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return relative_path.as_posix()


def _parse_curve_csv(payload: bytes, *, required_symbols: tuple[str, ...]) -> dict[str, dict[str, float]]:
    if not required_symbols:
        return _parse_dates_only(payload)

    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    normalized_fields = {_normalize_header(name): name for name in fieldnames if name is not None}
    date_field = normalized_fields.get("date")
    if date_field is None:
        raise ValueError("missing Date column")

    symbol_fields: dict[str, str] = {}
    for symbol in required_symbols:
        aliases = {_normalize_header(alias) for alias in _aliases_for_symbol(symbol)}
        field = next((normalized_fields[alias] for alias in aliases if alias in normalized_fields), None)
        if field is None:
            raise ValueError(f"missing Treasury column for {symbol}")
        symbol_fields[symbol] = field

    rows: dict[str, dict[str, float]] = {}
    for row in reader:
        observation_date = _parse_treasury_date(row.get(date_field))
        if observation_date is None:
            continue
        values: dict[str, float] = {}
        for symbol, field in symbol_fields.items():
            value = _parse_numeric(row.get(field))
            if value is not None:
                values[symbol] = value
        rows[observation_date.isoformat()] = values
    return rows


def _parse_dates_only(payload: bytes) -> dict[str, dict[str, float]]:
    """Parse dates for a curve that has no requested symbols.

    Fetching both official curves keeps the request and archive behavior
    deterministic for callers, even when a caller asks for a subset.  The
    unused curve still needs only a valid date column for alignment.
    """

    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    normalized_fields = {_normalize_header(name): name for name in fieldnames if name is not None}
    date_field = normalized_fields.get("date")
    if date_field is None:
        raise ValueError("missing Date column")
    rows: dict[str, dict[str, float]] = {}
    for row in reader:
        observation_date = _parse_treasury_date(row.get(date_field))
        if observation_date is not None:
            rows[observation_date.isoformat()] = {}
    return rows


def _source_ref(
    *,
    symbol: str,
    source_url: str,
    raw_path: str | None,
    retrieved_at: str,
    retrieved_date: str,
    observation_date: str | None,
    status: str,
    reason: str | None = None,
) -> dict[str, str]:
    ref = {
        "symbol": symbol,
        "source": TREASURY_RATES_SOURCE,
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "observation_cutoff_date": retrieved_date,
        "observation_date": observation_date or "unavailable",
        "unit": "percent",
        "curve": _CURVE_BY_SYMBOL[symbol],
        "status": status,
    }
    if raw_path is not None:
        ref["raw_path"] = raw_path
    if reason:
        ref["reason"] = reason
    return ref


def _validate_year(year: int) -> None:
    if isinstance(year, bool) or not isinstance(year, int) or not 1900 <= year <= 2100:
        raise ValueError("Treasury curve year must be a four-digit integer")


def _treasury_csv_url(*, year: int, curve_type: str) -> str:
    _validate_year(year)
    return f"{TREASURY_DAILY_RATES_CSV_URL}/{year}/all?_format=csv&field_tdr_date_value={year}&page=&type={curve_type}"


def _validate_retrieved_date(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError("retrieved_date must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"retrieved_date must be YYYY-MM-DD: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"retrieved_date must be YYYY-MM-DD: {value!r}")
    return parsed


def _validate_symbols(symbols: Iterable[str]) -> None:
    unsupported = [symbol for symbol in symbols if symbol not in _CURVE_BY_SYMBOL]
    if unsupported:
        raise ValueError(f"Unsupported Treasury rate symbols: {', '.join(unsupported)}")


def _aliases_for_symbol(symbol: str) -> tuple[str, ...]:
    return (_NOMINAL_COLUMNS if _CURVE_BY_SYMBOL[symbol] == "nominal" else _REAL_COLUMNS)[symbol]


def _normalize_header(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _parse_treasury_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_numeric(value: object) -> float | None:
    text = "" if value is None else str(value).strip().replace(",", "")
    if not text or text in {"N/A", "NA", "n/a", "na", ".", "-", "—", "null"}:
        return None
    try:
        numeric_value = float(text)
    except (TypeError, ValueError):
        return None
    return numeric_value if math.isfinite(numeric_value) else None


__all__ = [
    "TREASURY_DAILY_RATES_CSV_URL",
    "TREASURY_NOMINAL_CURVE_TYPE",
    "TREASURY_RATE_SOURCE",
    "TREASURY_RATE_SYMBOLS",
    "TREASURY_RATES_SOURCE",
    "TREASURY_REAL_CURVE_TYPE",
    "collect_treasury_rate_curves",
    "treasury_nominal_csv_url",
    "treasury_real_csv_url",
    "treasury_textview_url",
]
