from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from apps.analysis.snapshots.builder import build_analysis_snapshot, write_analysis_snapshot


def _macro_snapshot() -> dict:
    return {
        "as_of": "2026-05-14",
        "indicators": {"DGS10": {"value": 4.3}},
        "source_refs": [
            {"symbol": "DGS10", "source": "fred", "source_url": "https://fred.example/DGS10"},
            {"symbol": "DGS10", "source": "fred", "source_url": "https://fred.example/DGS10"},
        ],
    }


def _options_snapshot() -> dict:
    return {
        "version": "1.0",
        "trade_date": "2026-05-14",
        "data_source": {
            "status": "PRELIM",
            "product": "OG",
            "input_snapshot_ids": {
                "raw_file_sha256": "abc123",
                "raw_file_id": "42",
            },
        },
        "wall_scores": [{"strike": 3300, "rank": 1}],
    }


def test_analysis_snapshot_run_dir_rejects_unsafe_asset_and_trade_date(tmp_path: Path):
    from apps.analysis.snapshots.builder import analysis_snapshot_run_dir

    with pytest.raises(ValueError, match="asset"):
        analysis_snapshot_run_dir(tmp_path, asset="../XAUUSD", trade_date="2026-05-14", run_id="safe")
    with pytest.raises(ValueError, match="trade_date"):
        analysis_snapshot_run_dir(tmp_path, asset="XAUUSD", trade_date="../../escape", run_id="safe")


def test_build_available_macro_and_options_contains_required_fields():
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="test-run",
        macro_snapshot=_macro_snapshot(),
        options_snapshot=_options_snapshot(),
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    assert snapshot["version"] == "1.0"
    assert snapshot["snapshot_id"] == "XAUUSD:2026-05-14:test-run"
    assert snapshot["asset"] == "XAUUSD"
    assert snapshot["trade_date"] == "2026-05-14"
    assert snapshot["snapshot_time"] == "2026-05-14T10:00:00+08:00"
    assert snapshot["run_id"] == "test-run"
    assert snapshot["macro"]["status"] == "available"
    assert snapshot["macro"]["data"]["indicators"]["DGS10"]["value"] == 4.3
    assert snapshot["options"]["status"] == "available"
    assert snapshot["options"]["data"]["wall_scores"][0]["strike"] == 3300
    assert snapshot["input_snapshot_ids"]["macro"] == "macro:2026-05-14:test-run"
    assert snapshot["input_snapshot_ids"]["options"] == "options:2026-05-14:test-run"
    assert snapshot["input_snapshot_ids"]["options_detail"] == {
        "raw_file_sha256": "abc123",
        "raw_file_id": "42",
    }
    assert snapshot["positioning"]["status"] == "unavailable"
    assert "no_cot_gold" in snapshot["positioning"].get("reason", "")
    assert snapshot["news"] == {"status": "unavailable", "reason": "no_news_collected_points"}
    assert snapshot["technical"]["status"] == "unavailable"
    assert "no_xauusd" in snapshot["technical"].get("reason", "")
    assert isinstance(snapshot["source_refs"], list)


@pytest.mark.parametrize("macro_snapshot, options_snapshot", [(None, None), (_macro_snapshot(), None), (None, _options_snapshot())])
def test_build_marks_missing_macro_or_options_unavailable(macro_snapshot, options_snapshot):
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="missing-test",
        macro_snapshot=macro_snapshot,
        options_snapshot=options_snapshot,
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    expected_macro_status = "available" if macro_snapshot is not None else "unavailable"
    expected_options_status = "available" if options_snapshot is not None else "unavailable"
    assert snapshot["macro"]["status"] == expected_macro_status
    assert snapshot["options"]["status"] == expected_options_status
    if macro_snapshot is None:
        assert "data" not in snapshot["macro"]
        assert snapshot["macro"]["reason"] == "input_not_available"
    if options_snapshot is None:
        assert "data" not in snapshot["options"]
        assert snapshot["options"]["reason"] == "input_not_available"


def test_build_merges_and_deduplicates_source_refs():
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="source-ref-test",
        macro_snapshot=_macro_snapshot(),
        options_snapshot=None,
        source_refs=[
            {"symbol": "DGS10", "source": "fred", "source_url": "https://fred.example/DGS10"},
            {"symbol": "DXY", "source": "tradingview"},
        ],
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    assert len(snapshot["source_refs"]) == 2
    assert {tuple(sorted(ref.items())) for ref in snapshot["source_refs"]} == {
        tuple(sorted({"symbol": "DXY", "source": "tradingview"}.items())),
        tuple(sorted({"symbol": "DGS10", "source": "fred", "source_url": "https://fred.example/DGS10"}.items())),
    }


def test_write_analysis_snapshot_writes_non_empty_json_to_exact_path(tmp_path: Path):
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="write-test",
        macro_snapshot=_macro_snapshot(),
        options_snapshot=_options_snapshot(),
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    path = write_analysis_snapshot(snapshot, storage_root=tmp_path)

    assert path == tmp_path / "features" / "snapshots" / "XAUUSD" / "2026-05-14" / "write-test" / "premarket_snapshot.json"
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["snapshot_id"] == "XAUUSD:2026-05-14:write-test"


def test_write_analysis_snapshot_rejects_unsafe_run_id(tmp_path: Path):
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="../escape",
        macro_snapshot=None,
        options_snapshot=None,
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    with pytest.raises(ValueError, match="run_id"):
        write_analysis_snapshot(snapshot, storage_root=tmp_path)


def test_build_does_not_mutate_input_dictionaries():
    macro = _macro_snapshot()
    options = _options_snapshot()
    source_refs = [{"symbol": "DXY", "source": "tradingview"}]
    macro_before = copy.deepcopy(macro)
    options_before = copy.deepcopy(options)
    source_refs_before = copy.deepcopy(source_refs)

    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="immutability-test",
        macro_snapshot=macro,
        options_snapshot=options,
        source_refs=source_refs,
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    snapshot["macro"]["data"]["indicators"]["DGS10"]["value"] = 99
    snapshot["options"]["data"]["data_source"]["input_snapshot_ids"]["raw_file_id"] = "changed"
    snapshot["source_refs"].append({"symbol": "NEW"})

    assert macro == macro_before
    assert options == options_before
    assert source_refs == source_refs_before
