"""Tests for CME options analysis renderer (M4: P3-CME-OPT-04).

Covers:
- snapshot schema completeness
- report markdown contains Chinese headings and data-quality disclosure
- CLI smoke with existing fixture
"""

from __future__ import annotations

import json
from pathlib import Path

from apps.analysis.options.report import render_options_report_markdown
from apps.analysis.options.snapshot import build_options_snapshot, snapshot_to_dict

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "options"
SAMPLE_ROWS_PATH = FIXTURES / "sample_option_rows.json"


def _load_sample_rows() -> list[dict]:
    return json.loads(SAMPLE_ROWS_PATH.read_text())


def _option_row(
    *,
    expiry: str,
    strike: int = 4200,
    option_type: str = "CALL",
    settlement: float = 100.0,
    delta: float = 0.5,
    open_interest: int = 100,
) -> dict:
    return {
        "trade_date": "2026-05-06",
        "report_date": "2026-05-06",
        "product_code": "OG",
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type,
        "settlement": settlement,
        "delta": delta,
        "open_interest": open_interest,
        "oi_change": 0,
        "total_volume": 0,
        "block_volume": 0,
        "pnt_volume": 0,
        "globex_volume": 0,
        "outcry_volume": 0,
        "exercises": 0,
        "pt_change": 0.0,
    }


# -----------------------------------------------------------------------
# Data quality — PRELIM/FINAL counting (P3-REVIEW-FIX-05 blocker 2)
# -----------------------------------------------------------------------


class TestPrelimDataQualityCounting:
    """Verify that prelim_data count is correct per source status."""

    def _build(self, source_status: str) -> dict:
        rows = [_option_row(expiry="JUL26")]
        result = build_options_snapshot(
            rows, trade_date="2026-05-06",
            data_source_status=source_status,
        )
        return snapshot_to_dict(result)

    def test_prelim_status_increments_prelim_data(self) -> None:
        snap = self._build("PRELIM")
        assert snap["data_quality"]["categories"]["prelim_data"] > 0

    def test_preliminary_status_increments_prelim_data(self) -> None:
        """PRELIMINARY (from parser) must also count as prelim_data."""
        snap = self._build("PRELIMINARY")
        assert snap["data_quality"]["categories"]["prelim_data"] > 0

    def test_prelim_assumed_status_increments_prelim_data(self) -> None:
        """PRELIM_assumed (fallback) must also count as prelim_data."""
        snap = self._build("PRELIM_assumed")
        assert snap["data_quality"]["categories"]["prelim_data"] > 0

    def test_final_status_does_not_increment_prelim_data(self) -> None:
        snap = self._build("FINAL")
        assert snap["data_quality"]["categories"]["prelim_data"] == 0

    def test_unknown_status_does_not_increment_prelim_data(self) -> None:
        snap = self._build("UNKNOWN")
        assert snap["data_quality"]["categories"]["prelim_data"] == 0

    def test_status_propagates_to_data_source(self) -> None:
        """The status passed in appears verbatim in the snapshot data_source."""
        for status in ("PRELIM", "PRELIMINARY", "PRELIM_assumed", "FINAL", "UNKNOWN"):
            snap = self._build(status)
            assert snap["data_source"]["status"] == status


# -----------------------------------------------------------------------
# Snapshot schema
# -----------------------------------------------------------------------

class TestSnapshotSchema:
    """Verify the JSON snapshot has all required top-level keys."""

    def test_top_level_keys(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(
            rows,
            trade_date="2026-05-06",
            p0=4200.0,
        )
        snap = snapshot_to_dict(result)

        expected_keys = {
            "version", "trade_date", "generated_at", "data_source",
            "parameters", "normalization", "gex", "exposure",
            "walls", "wall_scores", "roll_signals", "intent",
            "support_resistance", "data_quality", "calibration",
            "audit", "wall_scores_scope", "wall_scores_full_chain_anomaly",
        }
        assert expected_keys <= set(snap.keys()), (
            f"Missing keys: {expected_keys - set(snap.keys())}, "
            f"Extra keys: {set(snap.keys()) - expected_keys}"
        )

    def test_data_source_fields(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(rows, trade_date="2026-05-06")
        snap = snapshot_to_dict(result)

        ds = snap["data_source"]
        assert ds["product"] == "OG"
        assert "JUL26" in ds["expiries"]
        assert ds["status"] == "UNKNOWN"  # default when not specified
        assert "input_snapshot_ids" in ds
        assert isinstance(ds["row_count"], int) and ds["row_count"] > 0

    def test_data_source_status_explicit(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(
            rows, trade_date="2026-05-06",
            data_source_status="PRELIM",
            data_source_url="https://example.com/bulletin.pdf",
            input_snapshot_ids={"raw_file_sha256": "abc123"},
        )
        snap = snapshot_to_dict(result)

        ds = snap["data_source"]
        assert ds["status"] == "PRELIM"
        assert ds["source_url"] == "https://example.com/bulletin.pdf"
        assert ds["input_snapshot_ids"] == {"raw_file_sha256": "abc123"}

    def test_parameters_fields(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(rows, trade_date="2026-05-06", p0=4200.0)
        snap = snapshot_to_dict(result)

        params = snap["parameters"]
        assert params["p0"] == 4200.0
        assert params["model"] == "black-76"
        assert isinstance(params["used_real_gex"], bool)
        assert params["f_source"] in ("user", "parity_inferred", "unavailable")

    def test_normalization_fields(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(rows, trade_date="2026-05-06")
        snap = snapshot_to_dict(result)

        norm = snap["normalization"]
        assert isinstance(norm["total_input_rows"], int)
        assert isinstance(norm["duplicates_merged"], int)
        assert isinstance(norm["rows_missing_settlement"], int)
        assert isinstance(norm["warnings"], list)

    def test_gex_separates_aggregate_gamma_zero_from_per_expiry_gex(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(rows, trade_date="2026-05-06", p0=4200.0)
        snap = snapshot_to_dict(result)

        assert snap["parameters"]["netgex_scope"] == "aggregate_across_expiries"
        aggregate = snap["gex"]["netgex_aggregate"]
        assert aggregate["gamma_zero"]["price"] == result.netgex.gamma_zero
        assert aggregate["gamma_zero"]["method"] == result.netgex.gamma_zero_method
        assert aggregate["gamma_zero"]["scope"] == "aggregate_across_expiries"
        assert "price_grid" in aggregate
        assert "net_gex_values" in aggregate

        by_expiry = snap["gex"]["by_expiry"]
        for expiry, gex_data in by_expiry.items():
            assert expiry in result.gex_top_by_expiry
            assert "gex_top" in gex_data
            assert "gamma_zero" not in gex_data

    def test_intent_fields(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(rows, trade_date="2026-05-06", p0=4200.0)
        snap = snapshot_to_dict(result)

        intent = snap["intent"]
        assert "type" in intent
        assert "score" in intent
        assert "confidence" in intent
        assert "evidence" in intent
        assert intent["type"].startswith("I")

    def test_data_quality_is_dict_with_warnings(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(rows, trade_date="2026-05-06")
        snap = snapshot_to_dict(result)

        dq = snap["data_quality"]
        assert "warnings" in dq
        assert isinstance(dq["warnings"], list)


# -----------------------------------------------------------------------
# Markdown report
# -----------------------------------------------------------------------

class TestReportMarkdown:
    """Verify the Chinese report has required sections."""

    def _report(self, p0: float | None = 4200.0) -> str:
        rows = _load_sample_rows()
        result = build_options_snapshot(rows, trade_date="2026-05-06", p0=p0)
        return render_options_report_markdown(result)

    def test_contains_title(self) -> None:
        report = self._report()
        assert "CME 黄金期权结构分析报告" in report

    def test_contains_prelim_disclaimer(self) -> None:
        report = self._report()
        assert "数据状态" in report
        assert "不构成交易建议" in report

    def test_contains_chinese_headings(self) -> None:
        report = self._report()
        required_headings = [
            "一句话结论",
            "数据口径",
            "GEX / Gamma Zero",
            "Delta / Vega / Theta Exposure",
            "订单墙 / WallScore",
            "Roll / 换月迁移",
            "I1-I4 机构意图",
            "支撑 / 阻力",
            "CME 大额持仓与近期流量",
            "三路径推演",
            "主/副剧本",
            "数据质量与局限性",
        ]
        for heading in required_headings:
            assert heading in report, f"Missing heading: {heading}"

    def test_contains_data_quality_disclosure(self) -> None:
        report = self._report()
        # Should have at least one data quality warning section
        assert "数据质量" in report

    def test_no_p0_shows_warning(self) -> None:
        report = self._report(p0=None)
        assert "价格口径" in report
        assert "report_p0" in report

    def test_with_p0_has_support_resistance(self) -> None:
        report = self._report(p0=4200.0)
        # With p0 provided, should have support/resistance section
        assert "支撑" in report
        assert "阻力" in report

    def test_live_strategy_has_ordered_unique_targets_and_valid_conditions(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(
            rows,
            trade_date="2026-05-06",
            p0=4200.0,
            live_p0=4050.0,
        )

        report = render_options_report_markdown(result)
        strategy = report.split("## 实盘策略卡片", 1)[1].split("## 主/副剧本", 1)[0]

        assert "- 第一目标：4100" in strategy
        assert "- 第二目标：4200" in strategy
        assert "- 第三目标：4200" not in strategy
        assert "- 第一目标：4000" in strategy
        assert "- 第二目标：3969" in strategy
        assert "价格跌回 Gamma Zero" not in strategy
        assert "重新站上 Gamma Zero（4078）" in strategy
        assert "**4000–4100 严格中段不适合追单，边界触发位不属于不交易区。**" in strategy

    def test_report_separates_absolute_oi_and_three_path_conditions(self) -> None:
        report = self._report(p0=4200.0)
        inventory = report.split("## CME 大额持仓与近期流量", 1)[1].split("## Delta", 1)[0]
        scenarios = report.split("## 三路径推演", 1)[1].split("## 实盘策略卡片", 1)[0]

        assert "不等同于 WallScore" in inventory
        assert "主战区筛选" in inventory
        assert "Total OI" in inventory
        assert "PNT/Block" in inventory
        assert "主路径：修复震荡" in scenarios
        assert "转强路径" in scenarios
        assert "转弱路径" in scenarios
        assert "**触发" in scenarios
        assert "**目标：**" in scenarios
        assert "**失效：**" in scenarios
        assert "概率约" not in scenarios

    def test_report_discloses_unverified_block_when_only_pnt_is_present(self) -> None:
        row = _option_row(expiry="JUL26", strike=4200)
        row["pnt_volume"] = 12
        result = build_options_snapshot([row], trade_date="2026-05-06", p0=4200.0)
        report = render_options_report_markdown(result)
        assert "Block 数据本次没有观测到非零值" in report

    def test_expiry_estimation_warning_uses_actual_contract_months(self) -> None:
        rows = [
            _option_row(expiry=expiry, option_type=option_type)
            for expiry in ("AUG26", "SEP26")
            for option_type in ("CALL", "PUT")
        ]
        result = build_options_snapshot(
            rows,
            trade_date="2026-05-06",
            p0=4200.0,
            user_f=4200.0,
        )

        report = render_options_report_markdown(result)

        assert "跨月 Gamma Zero 是 AUG26 与 SEP26" in report
        assert "AUG26 / SEP26 GEX 与 Gamma Zero 可能小幅变化" in report
        assert "跨月 Gamma Zero 是 JUN26 与 JUL26" not in report
        assert "JUN26 GEX 与 Gamma Zero 可能小幅变化" not in report


# -----------------------------------------------------------------------
# Snapshot-to-dict round-trip
# -----------------------------------------------------------------------

class TestSnapshotRoundTrip:
    """Verify snapshot dict is JSON-serializable."""

    def test_json_serializable(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(rows, trade_date="2026-05-06", p0=4200.0)
        snap = snapshot_to_dict(result)

        # Should not raise
        json_str = json.dumps(snap, ensure_ascii=False)
        assert len(json_str) > 100

        # Round-trip
        parsed = json.loads(json_str)
        assert parsed["trade_date"] == "2026-05-06"
        assert parsed["parameters"]["p0"] == 4200.0


# -----------------------------------------------------------------------
# Expiry filter
# -----------------------------------------------------------------------

class TestExpiryFilter:
    """Verify that expiries filter works."""

    def test_filter_single_expiry(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(
            rows, trade_date="2026-05-06", expiries=["JUL26"]
        )
        assert result.expiries == ["JUL26"]
        assert all(r.expiry == "JUL26" for r in result.normalized_rows)

    def test_no_rows_for_nonexistent_expiry(self) -> None:
        rows = _load_sample_rows()
        result = build_options_snapshot(
            rows, trade_date="2026-05-06", expiries=["DEC26"]
        )
        assert len(result.normalized_rows) == 0


# -----------------------------------------------------------------------
# Per-expiry regression
# -----------------------------------------------------------------------

class TestPerExpiryRegression:
    """Verify expiry isolation and per-expiry T handling."""

    def test_same_strike_type_does_not_leak_across_expiries(self) -> None:
        rows = [
            _option_row(expiry="JUN26", open_interest=100),
            _option_row(expiry="JUL26", open_interest=300),
        ]

        result = build_options_snapshot(rows, trade_date="2026-05-06", user_f=4200.0)

        jun_summary = result.exposure_summary_by_expiry["JUN26"]
        jul_summary = result.exposure_summary_by_expiry["JUL26"]

        assert jun_summary["net_dex"] != jul_summary["net_dex"]
        assert jun_summary["net_dex"] < jul_summary["net_dex"]
        assert len(result.gex_top_by_expiry["JUN26"]) == 1
        assert len(result.gex_top_by_expiry["JUL26"]) == 1

    def test_per_expiry_t_changes_greeks_for_same_price_inputs(self) -> None:
        rows = [
            _option_row(expiry="JUN26", open_interest=100),
            _option_row(expiry="JUL26", open_interest=100),
        ]

        result = build_options_snapshot(rows, trade_date="2026-05-06", user_f=4200.0)

        jun = next(item for item in result.exposures if item.expiry == "JUN26")
        jul = next(item for item in result.exposures if item.expiry == "JUL26")

        assert jun.iv is not None
        assert jul.iv is not None
        assert jun.iv != jul.iv
        assert abs(jun.theta_exposure_day) != abs(jul.theta_exposure_day)


# -----------------------------------------------------------------------
# Per-expiry enhanced data (M4 forward / GEX summary / IV skew)
# -----------------------------------------------------------------------

class TestPerExpiryEnhancedData:
    """Verify per-expiry forward, GEX summary, and IV skew fields."""

    def _build_snapshot(self, expiries=None, user_f=None) -> dict:
        rows = _load_sample_rows()
        result = build_options_snapshot(
            rows, trade_date="2026-05-06",
            expiries=expiries, user_f=user_f,
        )
        return snapshot_to_dict(result)

    def test_forward_by_expiry_exists_and_has_all_expiries(self) -> None:
        snap = self._build_snapshot()
        fbe = snap["parameters"]["forward_by_expiry"]
        assert isinstance(fbe, dict)
        assert "JUL26" in fbe
        assert "JUN26" in fbe
        for expiry, info in fbe.items():
            assert "f_value" in info
            assert "f_source" in info
            assert "warnings" in info

    def test_user_f_populates_all_expiries(self) -> None:
        snap = self._build_snapshot(user_f=4200.0)
        fbe = snap["parameters"]["forward_by_expiry"]
        for expiry, info in fbe.items():
            assert info["f_value"] == 4200.0
            assert info["f_source"] == "user"

    def test_parity_inferred_forward_differs_between_expiries(self) -> None:
        rows = [
            _option_row(expiry="JUN26", strike=4200, settlement=100.0,
                        option_type="CALL", open_interest=100),
            _option_row(expiry="JUN26", strike=4200, settlement=30.0,
                        option_type="PUT", open_interest=100),
            _option_row(expiry="JUL26", strike=4300, settlement=85.0,
                        option_type="CALL", open_interest=100),
            _option_row(expiry="JUL26", strike=4300, settlement=38.0,
                        option_type="PUT", open_interest=100),
        ]
        result = build_options_snapshot(rows, trade_date="2026-05-06")
        snap = snapshot_to_dict(result)
        fbe = snap["parameters"]["forward_by_expiry"]
        jun_f = fbe["JUN26"]["f_value"]
        jul_f = fbe["JUL26"]["f_value"]
        assert jun_f is not None and jul_f is not None
        assert abs(jun_f - 4270.0) < 1.0
        assert abs(jul_f - 4347.0) < 1.0
        assert jun_f != jul_f

    def test_gex_by_expiry_has_summary_and_iv_skew(self) -> None:
        snap = self._build_snapshot()
        by_expiry = snap["gex"]["by_expiry"]
        for expiry, gex_data in by_expiry.items():
            assert "gex_top" in gex_data
            assert "summary" in gex_data
            assert "iv_skew" in gex_data

            summary = gex_data["summary"]
            assert "f_value" in summary
            assert "gamma_zero" in summary
            assert "gamma_zero_method" in summary
            assert "net_gex" in summary
            assert "call_gex" in summary
            assert "put_gex" in summary
            assert "total_gex" in summary
            assert "structure" in summary
            assert summary["structure"] in ("net_call_dominated", "net_put_dominated", "balanced")

            iv_skew = gex_data["iv_skew"]
            assert "atm_iv" in iv_skew
            assert "call_25d_iv" in iv_skew
            assert "put_25d_iv" in iv_skew
            assert "skew_25d" in iv_skew
            assert "call_10d_iv" in iv_skew
            assert "put_10d_iv" in iv_skew
            assert "tail_skew_10d" in iv_skew
            assert "interpretation" in iv_skew

    def test_iv_skew_has_values_for_rich_fixture(self) -> None:
        snap = self._build_snapshot()
        for expiry, gex_data in snap["gex"]["by_expiry"].items():
            iv_skew = gex_data["iv_skew"]
            assert iv_skew["atm_iv"] is not None, f"{expiry} ATM IV is None"
            assert isinstance(iv_skew["atm_iv"], (int, float))
            assert 0.01 < iv_skew["atm_iv"] < 3.0

    def test_iv_skew_handles_no_data_gracefully(self) -> None:
        rows = [_option_row(expiry="JUN26", settlement=None, delta=None)]
        result = build_options_snapshot(rows, trade_date="2026-05-06", user_f=4200.0)
        snap = snapshot_to_dict(result)
        iv_skew = snap["gex"]["by_expiry"]["JUN26"]["iv_skew"]
        assert iv_skew["atm_iv"] is None
        assert "数据不足" in iv_skew["interpretation"]
