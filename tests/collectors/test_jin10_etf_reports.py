from __future__ import annotations

import json
from pathlib import Path

from apps.collectors.jin10.etf_reports import collect_jin10_etf_reports
from apps.features.market.etf_holdings import build_etf_holdings_context
from apps.parsers.jin10.etf_reports import parse_jin10_etf_report


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _Client:
    def get(self, url: str, *, params: dict, headers: dict):
        attr_id = params["attr_id"]
        return _Response(
            {
                "status": 200,
                "data": [
                    {
                        "trust": 1003.59 if attr_id == 1 else 15052.89,
                        "change": 4.566 if attr_id == 1 else -8.43,
                        "value": 110_000_000_000 if attr_id == 1 else 27_486_155_500,
                        "reported_on": "2026-07-20",
                        "updated_at": "2026-07-20T22:30:58.000Z",
                    }
                ],
            }
        )


def test_collect_parse_and_build_gold_silver_etf_context(tmp_path: Path) -> None:
    result = collect_jin10_etf_reports(
        retrieved_date="2026-07-21",
        storage_root=tmp_path,
        client=_Client(),
    )

    assert result.status == "success"
    assert result.items == []
    assert {ref["asset"] for ref in result.source_refs} == {"gold", "silver"}

    parsed: list[dict] = []
    for ref in result.source_refs:
        envelope = json.loads((tmp_path / ref["raw_path"]).read_text(encoding="utf-8"))
        report = parse_jin10_etf_report(
            envelope,
            raw_path=ref["raw_path"],
            reference_date="2026-07-21",
        )
        parsed.append(report.to_dict())

    context = build_etf_holdings_context(parsed)
    assert context["gold_etf_holdings_tonnes"] == 1003.59
    assert context["gold_etf_change_tonnes"] == 4.566
    assert context["silver_etf_holdings_tonnes"] == 15052.89
    assert context["silver_etf_change_tonnes"] == -8.43
    assert context["global_etf_flow"] == 4.566
    assert context["cross_metal_confirmation"] == "divergent"
    assert context["verification_status"] == "single_source"
    assert len(context["source_refs"]) == 2
