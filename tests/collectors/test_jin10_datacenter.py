from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apps.collectors.jin10.datacenter import DEFAULT_DATACENTER_SLUGS, fetch_datacenter_report
from apps.parsers.jin10.datacenter import datacenter_report_input_summary, parse_datacenter_js


ETF_GOLD_JS = """
var dataCenter_data = {"types":["黄金"],"kinds":["总库存(吨)","增持/减持(吨)","总价值(美元)"],"list":[{"date":"20200216","dataTime":"2020-02-16 08:01:03","datas":{"黄金":["923.99","0.00","46971717887.17"]}}],"minNo":4268,"maxNo":4270,"md5":"2b538ad24c22c4803ed9db17faee6717"};
"""

NONFARM_JS = """
var dataCenter_data = {"types":["美国非农"],"kinds":["前值(万人)","预期(万人)","公布值(万人)"],"list":[{"date":"20260606","dataTime":"2026-06-06 20:30:00","datas":{"美国非农":["18.5","13.0","13.9"]}}],"minNo":100,"maxNo":102,"md5":"abc123"};
"""

CFTC_NC_JS = """
var dataCenter_data = {"types":["欧元","日元","英镑"],"kinds":["多头","空头","净多头","净空头"],"list":[{"date":"20260610","dataTime":"2026-06-10 00:00:00","datas":{"欧元":["210000","180000","30000","0"],"日元":["95000","120000","0","25000"],"英镑":["50000","45000","5000","0"]}}],"minNo":200,"maxNo":202,"md5":"def456"};
"""


def test_parse_datacenter_js_normalizes_etf_gold_rows() -> None:
    parsed = parse_datacenter_js(
        ETF_GOLD_JS,
        slug="dc_etf_gold",
        report_name="黄金ETF持仓报告",
        source_refs=[{"source_key": "jin10_datacenter_reports", "raw_path": "raw.js"}],
    )

    data = parsed.to_dict()
    assert data["status"] == "ok"
    assert data["provider_role"] == "supplemental_source"
    assert data["slug"] == "dc_etf_gold"
    assert data["report_name"] == "黄金ETF持仓报告"
    assert data["as_of"] == "2020-02-16 08:01:03"
    assert data["types"] == ["黄金"]
    assert data["kinds"] == ["总库存(吨)", "增持/减持(吨)", "总价值(美元)"]
    assert data["min_no"] == 4268
    assert data["max_no"] == 4270
    assert data["checksum"] == "2b538ad24c22c4803ed9db17faee6717"
    assert data["freshness_status"] == "ok_stale"
    assert data["freshness_reason"] == "as_of_older_than_sla"
    assert data["rows"] == [
        {
            "date": "2020-02-16",
            "data_time": "2020-02-16 08:01:03",
            "values": [
                {"type": "黄金", "kind": "总库存(吨)", "value": "923.99"},
                {"type": "黄金", "kind": "增持/减持(吨)", "value": "0.00"},
                {"type": "黄金", "kind": "总价值(美元)", "value": "46971717887.17"},
            ],
            "raw": {
                "date": "20200216",
                "dataTime": "2020-02-16 08:01:03",
                "datas": {"黄金": ["923.99", "0.00", "46971717887.17"]},
            },
        }
    ]
    assert data["source_refs"] == [{"source_key": "jin10_datacenter_reports", "raw_path": "raw.js"}]


def test_parse_datacenter_js_marks_schema_changed_when_assignment_missing() -> None:
    parsed = parse_datacenter_js("window.other_payload = {};", slug="dc_etf_gold")

    data = parsed.to_dict()
    assert data["status"] == "schema_changed"
    assert data["rows"] == []
    assert data["source_refs"][0]["reason_code"] == "missing_dataCenter_data"


@dataclass
class _FakeResponse:
    text: str
    headers: dict[str, str] | None = None

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, html: str, js: str):
        self.html = html
        self.js = js
        self.urls: list[str] = []

    def get(self, url: str, **kwargs):
        self.urls.append(url)
        if "reportType" in url:
            return _FakeResponse(self.html, {"content-type": "text/html"})
        return _FakeResponse(self.js, {"content-type": "application/javascript"})


def test_fetch_datacenter_report_discovers_latest_js_and_archives_raw_files(tmp_path: Path) -> None:
    html = """
    <html><head><title>黄金ETF持仓报告</title></head>
    <body>
      <script>var nameType='dc_etf_gold';</script>
      <script src="//cdn.jin10.com/dc/reports/dc_etf_gold_latest.js?20260613"></script>
    </body></html>
    """
    client = _FakeClient(html=html, js=ETF_GOLD_JS)

    result = fetch_datacenter_report(
        slug="dc_etf_gold",
        storage_root=tmp_path,
        retrieved_date="2026-06-13",
        client=client,
    )

    data = result.to_dict()
    assert data["status"] == "ok"
    assert data["slug"] == "dc_etf_gold"
    assert data["name_type"] == "dc_etf_gold"
    assert data["script_url"] == "https://cdn.jin10.com/dc/reports/dc_etf_gold_latest.js?20260613"
    assert data["raw_html_path"] == "raw/jin10/datacenter/2026-06-13/dc_etf_gold/shell.html"
    assert data["raw_js_path"] == "raw/jin10/datacenter/2026-06-13/dc_etf_gold/latest.js"
    assert (tmp_path / data["raw_html_path"]).exists()
    assert (tmp_path / data["raw_js_path"]).exists()
    assert data["source_refs"][0]["source_key"] == "jin10_datacenter_reports"
    assert data["source_refs"][0]["access_method"] == "js_data_script"
    assert client.urls == [
        "https://datacenter.jin10.com/reportType/dc_etf_gold",
        "https://cdn.jin10.com/dc/reports/dc_etf_gold_latest.js?20260613",
    ]


def test_default_slugs_registry_contains_three_pilot_slugs() -> None:
    assert "dc_etf_gold" in DEFAULT_DATACENTER_SLUGS
    assert "dc_nonfarm_payrolls" in DEFAULT_DATACENTER_SLUGS
    assert "dc_cftc_nc_report" in DEFAULT_DATACENTER_SLUGS
    assert len(DEFAULT_DATACENTER_SLUGS) == 3


def test_parse_datacenter_js_normalizes_nonfarm_payrolls_rows() -> None:
    parsed = parse_datacenter_js(
        NONFARM_JS,
        slug="dc_nonfarm_payrolls",
        report_name="美国非农就业报告",
    )

    data = parsed.to_dict()
    assert data["status"] == "ok"
    assert data["slug"] == "dc_nonfarm_payrolls"
    assert data["types"] == ["美国非农"]
    assert data["kinds"] == ["前值(万人)", "预期(万人)", "公布值(万人)"]
    assert data["freshness_status"] == "ok_current"
    assert data["freshness_reason"] == "within_sla"
    assert len(data["rows"]) == 1
    assert data["rows"][0]["values"][0] == {"type": "美国非农", "kind": "前值(万人)", "value": "18.5"}


def test_parse_datacenter_js_normalizes_cftc_nc_report_rows() -> None:
    parsed = parse_datacenter_js(
        CFTC_NC_JS,
        slug="dc_cftc_nc_report",
        report_name="CFTC 外汇非商业持仓报告",
    )

    data = parsed.to_dict()
    assert data["status"] == "ok"
    assert data["slug"] == "dc_cftc_nc_report"
    assert data["types"] == ["欧元", "日元", "英镑"]
    assert len(data["rows"]) == 1
    values = data["rows"][0]["values"]
    assert len(values) == 12  # 3 types * 4 kinds
    assert values[0] == {"type": "欧元", "kind": "多头", "value": "210000"}


def test_fetch_datacenter_report_handles_nonfarm_payrolls(tmp_path: Path) -> None:
    html = """
    <html><head><title>美国非农就业报告</title></head>
    <body>
      <script>var nameType='dc_nonfarm_payrolls';</script>
      <script src="//cdn.jin10.com/dc/reports/dc_nonfarm_payrolls_latest.js?20260613"></script>
    </body></html>
    """
    client = _FakeClient(html=html, js=NONFARM_JS)

    result = fetch_datacenter_report(
        slug="dc_nonfarm_payrolls",
        storage_root=tmp_path,
        retrieved_date="2026-06-13",
        client=client,
    )

    data = result.to_dict()
    assert data["status"] == "ok"
    assert data["slug"] == "dc_nonfarm_payrolls"
    assert data["raw_html_path"] == "raw/jin10/datacenter/2026-06-13/dc_nonfarm_payrolls/shell.html"


def test_fetch_datacenter_report_handles_cftc_nc_report(tmp_path: Path) -> None:
    html = """
    <html><head><title>CFTC 外汇非商业持仓报告</title></head>
    <body>
      <script>var nameType='dc_cftc_nc_report';</script>
      <script src="//cdn.jin10.com/dc/reports/dc_cftc_nc_report_latest.js?20260613"></script>
    </body></html>
    """
    client = _FakeClient(html=html, js=CFTC_NC_JS)

    result = fetch_datacenter_report(
        slug="dc_cftc_nc_report",
        storage_root=tmp_path,
        retrieved_date="2026-06-13",
        client=client,
    )

    data = result.to_dict()
    assert data["status"] == "ok"
    assert data["slug"] == "dc_cftc_nc_report"
    assert data["raw_html_path"] == "raw/jin10/datacenter/2026-06-13/dc_cftc_nc_report/shell.html"


def test_datacenter_report_input_summary_marks_supplemental_source() -> None:
    parsed = parse_datacenter_js(
        ETF_GOLD_JS,
        slug="dc_etf_gold",
        report_name="黄金ETF持仓报告",
        source_refs=[{"source_key": "jin10_datacenter_reports", "raw_path": "raw.js"}],
    )

    summary = datacenter_report_input_summary(parsed)

    assert summary["source_key"] == "jin10_datacenter_reports"
    assert summary["slug"] == "dc_etf_gold"
    assert summary["report_name"] == "黄金ETF持仓报告"
    assert summary["provider_role"] == "supplemental_source"
    assert summary["verification_status"] == "single_source"
    assert summary["official_primary"] is False
    assert summary["status"] == "ok"
    assert summary["freshness_status"] == "ok_stale"
    assert summary["freshness_reason"] == "as_of_older_than_sla"
    assert summary["usable_for_production_conclusions"] is False
    assert summary["as_of"] == "2020-02-16 08:01:03"
    assert summary["row_count"] == 1
    assert summary["latest_values"]["总库存(吨)"] == "923.99"
    assert "official facts must be confirmed" in summary["warnings"][0]
    assert "stale" in summary["warnings"][1]


def test_datacenter_report_input_summary_includes_source_refs() -> None:
    parsed = parse_datacenter_js(ETF_GOLD_JS, slug="dc_etf_gold")
    custom_refs = [{"source_key": "custom", "status": "ok"}]

    summary = datacenter_report_input_summary(parsed, source_refs=custom_refs)

    assert summary["source_refs"] == custom_refs
