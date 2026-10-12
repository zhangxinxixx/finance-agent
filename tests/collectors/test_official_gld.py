from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from apps.collectors.etf.official_gld import (
    GLD_HISTORICAL_ARCHIVE_URL,
    GLD_NAV_HISTORY_URL,
    collect_official_gld,
)
from apps.features.market.official_etf import build_official_gld_context
from apps.parsers.etf.official_gld import (
    parse_gld_historical_archive,
    parse_gld_nav_history,
)


def _xlsx(sheet_name: str, rows: list[list[object]]) -> bytes:
    def cell(column: int, row_number: int, value: object) -> str:
        reference = f"{chr(ord('A') + column)}{row_number}"
        if isinstance(value, str):
            return f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
        return f'<c r="{reference}"><v>{value}</v></c>'

    sheet_rows = []
    for row_number, values in enumerate(rows, start=1):
        cells = "".join(cell(column, row_number, value) for column, value in enumerate(values))
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return output.getvalue()


NAV_ROWS = [
    ["Fund Name: SPDR Gold Shares"],
    ["Ticker Symbol:", "GLD"],
    [],
    ["Date", "NAV", "Shares Outstanding", "Total Net Assets"],
    ["04-Sep-2026", 404.918175, 368700000, 149293331231.18],
    ["03-Sep-2026", 409.67017, 369200000, 151250226745.46],
    ["28-Aug-2026", 418.467636, 365300000, 152866227351.11],
    ["27-Aug-2026", 415.0, 364900000, 151000000000.0],
]

HOLDINGS_ROWS = [
    [
        "Date",
        "Closing Price",
        "Total Ounces of Gold in the Trust",
        "Tonnes of Gold",
        "Total Net Asset Value in the Trust",
    ],
    ["03-Sep-2026", 410.22, 33870494.55, 1053.48, 151250226745.46],
    ["28-Aug-2026", 408.89, 33512833.02, 1042.36, 152866227351.11],
    ["27-Aug-2026", 405.0, 33480000.0, 1041.34, 151000000000.0],
]


def test_official_gld_parsers_select_date_and_reject_incomplete_rows() -> None:
    nav = parse_gld_nav_history(
        _xlsx("navhist", NAV_ROWS),
        cutoff_date=date(2026, 9, 3),
    )
    holdings = parse_gld_historical_archive(
        _xlsx("US GLD Historical Archive", HOLDINGS_ROWS),
        cutoff_date=date(2026, 9, 3),
    )

    latest_nav, previous_nav = nav.latest_pair()
    latest_holdings, previous_holdings = holdings.latest_pair()
    assert latest_nav.to_dict() == {
        "report_date": "2026-09-03",
        "nav_per_share": 409.67017,
        "shares_outstanding": 369200000.0,
        "total_net_assets_usd": 151250226745.46,
    }
    assert previous_nav.report_date.isoformat() == "2026-08-28"
    assert latest_holdings.gold_holdings_tonnes == 1053.48
    assert latest_holdings.gold_holdings_ounces == 33870494.55
    assert previous_holdings.gold_holdings_tonnes == 1042.36
    assert nav.skipped_rows == 0
    assert holdings.skipped_rows == 0


def test_official_gld_weekly_anchor_uses_target_date_or_previous_available() -> None:
    nav = parse_gld_nav_history(
        _xlsx("navhist", NAV_ROWS),
        cutoff_date=date(2026, 9, 4),
    )
    latest_nav, _ = nav.latest_pair()
    assert latest_nav.report_date == date(2026, 9, 4)
    assert nav.weekly_anchor(latest_nav).report_date == date(2026, 8, 28)

    fallback_rows = [row for row in NAV_ROWS if not row or row[0] != "28-Aug-2026"]
    fallback = parse_gld_nav_history(
        _xlsx("navhist", fallback_rows),
        cutoff_date=date(2026, 9, 4),
    )
    assert fallback.weekly_anchor().report_date == date(2026, 8, 27)


class _Response:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Client:
    def __init__(self, responses: dict[str, bytes]):
        self.responses = responses
        self.urls: list[str] = []

    def get(self, url: str) -> _Response:
        self.urls.append(url)
        return _Response(self.responses[url])


def test_official_gld_default_client_respects_configured_network_environment(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _EnvironmentClient(_Client):
        def __init__(self, **kwargs: object):
            super().__init__(
                {
                    GLD_NAV_HISTORY_URL: _xlsx("navhist", NAV_ROWS),
                    GLD_HISTORICAL_ARCHIVE_URL: _xlsx("US GLD Historical Archive", HOLDINGS_ROWS),
                }
            )
            captured.update(kwargs)

        def close(self) -> None:
            return None

    monkeypatch.setattr("apps.collectors.etf.official_gld.httpx.Client", _EnvironmentClient)

    result = collect_official_gld(
        retrieved_date="2026-09-03",
        storage_root=tmp_path,
    )

    assert result.unavailable_symbols == []
    assert captured["trust_env"] is True


def test_official_gld_retries_transient_source_failure_and_records_attempts(tmp_path: Path) -> None:
    class _FlakyClient(_Client):
        def __init__(self) -> None:
            super().__init__(
                {
                    GLD_NAV_HISTORY_URL: _xlsx("navhist", NAV_ROWS),
                    GLD_HISTORICAL_ARCHIVE_URL: _xlsx("US GLD Historical Archive", HOLDINGS_ROWS),
                }
            )
            self.holdings_attempts = 0

        def get(self, url: str) -> _Response:
            if url == GLD_HISTORICAL_ARCHIVE_URL and self.holdings_attempts == 0:
                self.holdings_attempts += 1
                raise RuntimeError("temporary EOF")
            return super().get(url)

    client = _FlakyClient()
    result = collect_official_gld(
        retrieved_date="2026-09-03",
        storage_root=tmp_path,
        client=client,
    )

    assert result.unavailable_symbols == []
    holdings_ref = next(ref for ref in result.source_refs if ref["source"] == "spdr_gld")
    assert holdings_ref["attempt_count"] == "2"
    assert "attempt_1:RuntimeError: temporary EOF" in holdings_ref["attempt_failures"]


def test_official_gld_final_failure_records_exact_retry_count(tmp_path: Path) -> None:
    class _FailingClient:
        def get(self, url: str) -> _Response:
            raise RuntimeError(f"offline: {url}")

    result = collect_official_gld(
        retrieved_date="2026-09-03",
        storage_root=tmp_path,
        client=_FailingClient(),
    )

    assert set(result.unavailable_symbols) == {"GLD_shares_outstanding", "GLD_gold_holdings_tonnes"}
    assert {ref["attempt_count"] for ref in result.source_refs} == {"3"}
    assert all(ref["attempt_failures"].count("attempt_") == 3 for ref in result.source_refs)


def test_official_gld_parse_failure_after_retry_records_successful_attempt(tmp_path: Path) -> None:
    class _RetryThenParseFailureClient:
        def __init__(self) -> None:
            self.nav_attempts = 0

        def get(self, url: str) -> _Response:
            if url == GLD_NAV_HISTORY_URL:
                self.nav_attempts += 1
                if self.nav_attempts == 1:
                    raise RuntimeError("temporary EOF")
                return _Response(b"not-an-xlsx")
            return _Response(_xlsx("US GLD Historical Archive", HOLDINGS_ROWS))

    result = collect_official_gld(
        retrieved_date="2026-09-03",
        storage_root=tmp_path,
        client=_RetryThenParseFailureClient(),
    )

    assert "GLD_shares_outstanding" in result.unavailable_symbols
    nav_ref = next(ref for ref in result.source_refs if ref["source"] == "ssga_gld")
    assert nav_ref["attempt_count"] == "2"
    assert "attempt_1:RuntimeError: temporary EOF" in nav_ref["attempt_failures"]


def test_collect_and_build_official_gld_context_keeps_aum_level_only(tmp_path: Path) -> None:
    client = _Client(
        {
            GLD_NAV_HISTORY_URL: _xlsx("navhist", NAV_ROWS),
            GLD_HISTORICAL_ARCHIVE_URL: _xlsx("US GLD Historical Archive", HOLDINGS_ROWS),
        }
    )
    result = collect_official_gld(
        retrieved_date="2026-09-03",
        storage_root=tmp_path,
        client=client,
    )

    assert client.urls == [GLD_NAV_HISTORY_URL, GLD_HISTORICAL_ARCHIVE_URL]
    assert result.unavailable_symbols == []
    points = {point.symbol: point for point in result.points}
    assert points["GLD_shares_outstanding"].value == 369200000
    assert points["GLD_shares_outstanding_delta"].value == 3900000
    assert points["GLD_shares_outstanding_weekly_anchor"].date == "2026-08-27"
    assert points["GLD_shares_outstanding_weekly_anchor"].value == 364900000
    assert points["GLD_shares_outstanding_weekly_anchor"].source == "ssga_gld"
    assert points["GLD_shares_outstanding_weekly_anchor"].raw_path == points["GLD_shares_outstanding"].raw_path
    assert points["GLD_gold_holdings_tonnes"].value == 1053.48
    assert points["GLD_gold_holdings_tonnes_delta"].value == 11.12
    assert points["GLD_gold_holdings_tonnes_weekly_anchor"].date == "2026-08-27"
    assert points["GLD_gold_holdings_tonnes_weekly_anchor"].value == 1041.34
    assert points["GLD_gold_holdings_tonnes_weekly_anchor"].source == "spdr_gld"
    assert points["GLD_gold_holdings_tonnes_weekly_anchor"].raw_path == points["GLD_gold_holdings_tonnes"].raw_path
    assert points["GLD_gold_holdings_ounces_delta"].value == 357661.53
    assert all(not Path(point.raw_path).is_absolute() for point in result.points)
    assert {ref["source"] for ref in result.source_refs} == {"ssga_gld", "spdr_gld"}
    assert all(ref["provider_role"] == "official_primary" for ref in result.source_refs)
    assert all(ref["status"] == "ok" for ref in result.source_refs)
    raw_dir = tmp_path / "raw/etf/spdr/2026-09-03"
    nav_archives = list(raw_dir.glob("gld_nav_history-*.xlsx"))
    holdings_archives = list(raw_dir.glob("gld_historical_archive-*.xlsx"))
    assert len(nav_archives) == 1
    assert len(holdings_archives) == 1
    second_result = collect_official_gld(
        retrieved_date="2026-09-03",
        storage_root=tmp_path,
        client=client,
    )
    assert second_result.unavailable_symbols == []
    assert len(list(raw_dir.glob("gld_nav_history-*.xlsx"))) == 2
    assert len(list(raw_dir.glob("gld_historical_archive-*.xlsx"))) == 2

    context = build_official_gld_context(
        points=[point.to_dict() for point in result.points],
        source_refs=result.source_refs,
    )
    assert context["status"] == "available"
    assert context["fund_scope"] == "single_fund"
    assert context["shares_outstanding"] == 369200000
    assert context["shares_delta"] == 3900000
    assert context["shares_previous_value"] == 365300000
    assert context["shares_previous_reported_on"] == "2026-08-28"
    assert context["shares_weekly_anchor_value"] == 364900000
    assert context["shares_weekly_anchor_date"] == "2026-08-27"
    assert context["shares_weekly_delta"] == 4300000
    assert context["gold_holdings_tonnes"] == 1053.48
    assert context["gold_holdings_tonnes_delta"] == 11.12
    assert context["gold_holdings_tonnes_previous_value"] == 1042.36
    assert context["gold_holdings_tonnes_previous_reported_on"] == "2026-08-28"
    assert context["gold_holdings_tonnes_weekly_anchor_value"] == 1041.34
    assert context["gold_holdings_tonnes_weekly_anchor_date"] == "2026-08-27"
    assert context["gold_holdings_tonnes_weekly_delta"] == 12.14
    assert context["date_alignment"] == "same_date"
    assert context["total_net_assets_usd"] == 151250226745.46
    assert context["total_net_assets_reported_on"] == "2026-09-03"
    assert context["total_net_asset_value_reported_on"] == "2026-09-03"
    assert context["global_etf_flow"] is None
    assert context["north_america_etf_flow"] is None
    assert "total_net_assets_delta" not in context
    assert "aum_flow_usd" not in context


def test_official_gld_parser_does_not_turn_bad_numeric_rows_into_zero() -> None:
    rows = [
        NAV_ROWS[3],
        ["03-Sep-2026", "not-a-nav", 369200000, 151250226745.46],
    ]
    parsed = parse_gld_nav_history(_xlsx("navhist", rows), cutoff_date=date(2026, 9, 3))
    assert parsed.rows == ()
    assert parsed.skipped_rows == 1


@pytest.mark.parametrize(
    ("parser", "sheet_name", "rows", "message"),
    [
        (
            parse_gld_nav_history,
            "navhist",
            NAV_ROWS[:6] + [["03-Sep-2026", 409.67, 369200001, 151250226745.46]],
            "Conflicting duplicate GLD NAV row",
        ),
        (
            parse_gld_historical_archive,
            "US GLD Historical Archive",
            HOLDINGS_ROWS[:2] + [["03-Sep-2026", 410.22, 33870494.55, 1053.49, 151250226745.46]],
            "Conflicting duplicate GLD holdings row",
        ),
    ],
)
def test_official_gld_parsers_reject_conflicting_duplicate_dates(parser, sheet_name, rows, message) -> None:
    with pytest.raises(ValueError, match=message):
        parser(_xlsx(sheet_name, rows), cutoff_date=date(2026, 9, 3))


def test_official_gld_rejects_noncanonical_retrieved_date_before_archiving(tmp_path: Path) -> None:
    result = collect_official_gld(
        retrieved_date="2026-09-03/escape",
        storage_root=tmp_path,
    )

    assert result.points == []
    assert set(result.unavailable_symbols) == {"GLD_shares_outstanding", "GLD_gold_holdings_tonnes"}
    assert all(ref["status"] == "unavailable" for ref in result.source_refs)
    assert list(tmp_path.rglob("*")) == []


def test_official_gld_context_does_not_call_two_source_failure_partial() -> None:
    context = build_official_gld_context(
        points=[],
        source_refs=[
            {
                "source": "ssga_gld",
                "source_url": GLD_NAV_HISTORY_URL,
                "source_tier": "official",
                "status": "unavailable",
                "reason": "timeout",
            },
            {
                "source": "spdr_gld",
                "source_url": GLD_HISTORICAL_ARCHIVE_URL,
                "source_tier": "official",
                "status": "unavailable",
                "reason": "timeout",
            },
        ],
    )

    assert context["status"] == "unavailable"
    assert context["missing_data"] == ("shares_outstanding", "gold_holdings_tonnes")


def test_official_gld_context_does_not_call_one_source_same_date() -> None:
    context = build_official_gld_context(
        points=[
            {"symbol": "GLD_shares_outstanding", "date": "2026-09-04", "value": 368700000},
            {"symbol": "GLD_shares_outstanding_weekly_anchor", "date": "2026-08-28", "value": 365300000},
        ],
        source_refs=[
            {"source": "ssga_gld", "source_url": GLD_NAV_HISTORY_URL, "source_tier": "official", "raw_path": "raw/nav.xlsx"},
        ],
    )

    assert context["status"] == "partial"
    assert context["date_alignment"] == "missing"
    assert context["missing_data"] == ("gold_holdings_tonnes",)


def test_official_gld_context_marks_different_source_dates_partial() -> None:
    context = build_official_gld_context(
        points=[
            {"symbol": "GLD_shares_outstanding", "date": "2026-09-04", "value": 368700000},
            {"symbol": "GLD_shares_outstanding_prev", "date": "2026-09-03", "value": 369200000},
            {"symbol": "GLD_shares_outstanding_weekly_anchor", "date": "2026-08-28", "value": 365300000},
            {"symbol": "GLD_gold_holdings_tonnes", "date": "2026-09-03", "value": 1053.48},
            {"symbol": "GLD_gold_holdings_tonnes_prev", "date": "2026-09-02", "value": 1056.62},
            {"symbol": "GLD_gold_holdings_tonnes_weekly_anchor", "date": "2026-08-27", "value": 1041.34},
            {"symbol": "GLD_total_net_assets_usd", "date": "2026-09-04", "value": 149293331231.18},
            {"symbol": "GLD_total_net_asset_value_usd", "date": "2026-09-03", "value": 151250226745.46},
        ],
        source_refs=[
            {"source": "ssga_gld", "source_url": GLD_NAV_HISTORY_URL, "source_tier": "official", "raw_path": "raw/nav.xlsx"},
            {"source": "spdr_gld", "source_url": GLD_HISTORICAL_ARCHIVE_URL, "source_tier": "official", "raw_path": "raw/holdings.xlsx"},
        ],
    )

    assert context["status"] == "partial"
    assert context["date_alignment"] == "different_source_dates"
    assert context["missing_data"] == ("shares_holdings_date_alignment",)
    assert context["shares_delta"] == -500000
    assert context["gold_holdings_tonnes_delta"] == -3.14
    assert context["total_net_assets_reported_on"] == "2026-09-04"
    assert context["total_net_asset_value_reported_on"] == "2026-09-03"
