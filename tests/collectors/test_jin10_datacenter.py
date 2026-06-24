from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apps.collectors.jin10.datacenter import fetch_datacenter_report
from apps.parsers.jin10.datacenter import parse_datacenter_js


ETF_GOLD_JS = """
var dataCenter_data = {"types":["黄金"],"kinds":["总库存(吨)","增持/减持(吨)","总价值(美元)"],"list":[{"date":"20200216","dataTime":"2020-02-16 08:01:03","datas":{"黄金":["923.99","0.00","46971717887.17"]}}],"minNo":4268,"maxNo":4270,"md5":"2b538ad24c22c4803ed9db17faee6717"};
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
