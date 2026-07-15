#!/usr/bin/env python3
"""CLI entry point for CME options analysis.

Usage:
    uv run python scripts/run_options_analysis.py \
        --trade-date 2026-05-14 \
        --product OG \
        --expiries JUN26,JUL26 \
        --p0 3350 \
        --parsed-json tests/fixtures/options/sample_option_rows.json

Outputs:
    <out-dir>/options_analysis.json
    <out-dir>/options_analysis.md
    <out-dir>/options_visual_report.json
    <out-dir>/options_visual_report.html
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Ensure project root is on PYTHONPATH for direct CLI invocation
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CME gold options structure analysis renderer"
    )
    parser.add_argument(
        "--trade-date",
        required=True,
        help="Trade date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--product",
        default="OG",
        help="Product code (default: OG)",
    )
    parser.add_argument(
        "--expiries",
        default=None,
        help="Comma-separated expiry codes (e.g. JUL26,AUG26). Default: nearest two expiries for the trade date/product.",
    )
    parser.add_argument(
        "--all-expiries",
        action="store_true",
        help="Use all expiries found in the input. Default is nearest two expiries.",
    )
    parser.add_argument(
        "--p0",
        type=float,
        default=None,
        help="End-of-day structure anchor/report_p0. Prefer same trade_date settlement or parity-inferred F; if analysis range is not explicit, report_p0±1000 is used.",
    )
    parser.add_argument(
        "--analysis-strike-min",
        type=int,
        default=None,
        help="Main analysis lower strike bound. Defaults to p0-1000 if p0 is given, else 3800.",
    )
    parser.add_argument(
        "--analysis-strike-max",
        type=int,
        default=None,
        help="Main analysis upper strike bound. Defaults to p0+1000 if p0 is given, else 5000.",
    )
    parser.add_argument(
        "--analysis-range-mode",
        choices=["auto", "normal"],
        default="auto",
        help="Main range mode. auto = explicit range, else p0±1000, else 3800–5000. normal = F±Nσ with minimum half-width.",
    )
    parser.add_argument(
        "--analysis-range-sigma",
        type=float,
        default=2.0,
        help="Sigma multiplier for --analysis-range-mode normal (default: 2).",
    )
    parser.add_argument(
        "--analysis-range-min-half-width",
        type=int,
        default=500,
        help="Minimum half-width in dollars for normal range mode (default: 500).",
    )
    parser.add_argument(
        "--p0-source",
        choices=["manual", "auto", "forward", "jin10"],
        default="manual",
        help="Report P0 source when --p0 is not supplied. manual=no auto lookup; forward=near-expiry parity forward; auto=forward. Deprecated jin10 is treated as forward for report_p0; use --live-p0-source jin10 for realtime price.",
    )
    parser.add_argument(
        "--p0-field",
        choices=["close", "open"],
        default="close",
        help="Jin10 quote field to use as P0 when --p0-source is jin10/auto (default: close; use open for same-day opening reference).",
    )
    parser.add_argument(
        "--p0-code",
        default="XAUUSD",
        help="Deprecated alias for --live-p0-code when using legacy --p0-source jin10 (default: XAUUSD).",
    )
    parser.add_argument(
        "--live-p0",
        type=float,
        default=None,
        help="Intraday/live price used only for strategy card and current-price sorting. Does not affect Black-76/GEX or report_p0.",
    )
    parser.add_argument(
        "--live-p0-source",
        choices=["manual", "auto", "jin10", "none"],
        default="auto",
        help="Live P0 source for intraday support/resistance and strategy. Default auto fetches Jin10 MCP quote; use none to disable live price.",
    )
    parser.add_argument(
        "--live-p0-field",
        choices=["close", "open"],
        default="close",
        help="Jin10 quote field to use as live_p0 (default: close).",
    )
    parser.add_argument(
        "--live-p0-code",
        default="XAUUSD",
        help="Jin10 quote code for live_p0 lookup (default: XAUUSD).",
    )
    parser.add_argument(
        "--f",
        type=float,
        default=None,
        help="User-supplied forward price override",
    )
    parser.add_argument(
        "--parsed-json",
        required=True,
        help="Path to parsed JSON file or xlsx workbook with CME option rows",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory (default: storage/outputs/cme_options/<trade-date>)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run id used for AgentOutput traceability. Defaults to raw_file_sha256 prefix or product+date.",
    )
    parser.add_argument(
        "--data-source-status",
        default=None,
        help="Data source status: PRELIM, FINAL, or UNKNOWN (default)",
    )
    parser.add_argument(
        "--data-source-url",
        default=None,
        help="CME source PDF URL for provenance tracking",
    )
    return parser.parse_args()


def _excel_col_index(col: str) -> int:
    n = 0
    for ch in col:
        if not ch.isalpha():
            continue
        n = n * 26 + (ord(ch.upper()) - 64)
    return n


def _excel_col_name(index: int) -> str:
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _to_int(value: object, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_rows(input_path: Path) -> list[dict]:
    suffix = input_path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("detail_rows"), list):
            return [_parsed_detail_row_to_analysis_row(row, payload) for row in payload["detail_rows"]]
        raise ValueError("input JSON must be an array of option row dicts or a CME parse result object with detail_rows")
    if suffix in {".xlsx", ".xlsm"}:
        return _load_rows_from_xlsx(input_path)
    raise ValueError(f"unsupported input format: {input_path.suffix}")


def _parsed_detail_row_to_analysis_row(row: dict, payload: dict) -> dict:
    trade_date = str(row.get("trade_date") or payload.get("trade_date") or "")
    product = str(row.get("product_code") or row.get("product") or payload.get("product") or "OG")
    status = str(row.get("source") or payload.get("status") or "UNKNOWN")
    return {
        **row,
        "source_file": str(row.get("source_file") or payload.get("bulletin") or ""),
        "trade_date": trade_date,
        "report_date": str(row.get("report_date") or trade_date),
        "product_code": product,
        "product_name": str(row.get("product_name") or product),
        "expiry": str(row.get("expiry") or ""),
        "option_type": str(row.get("option_type") or "").upper(),
        "strike": _to_int(row.get("strike")),
        "settlement": _to_float(row.get("settlement")),
        "delta": _to_float(row.get("delta")),
        "delta_raw": _to_float(row.get("delta_raw") if "delta_raw" in row else row.get("delta")),
        "open_interest": _to_int(row.get("open_interest")),
        "oi_change": _to_int(row.get("oi_change")),
        "total_volume": _to_int(row.get("total_volume")),
        "block_volume": _to_int(row.get("block_volume")),
        "pnt_volume": _to_int(row.get("pnt_volume")),
        "globex_volume": _to_int(row.get("globex_volume")),
        "outcry_volume": _to_int(row.get("outcry_volume")),
        "exercises": _to_int(row.get("exercises")),
        "pt_change": _to_float(row.get("pt_change")),
        "source": status,
    }


def _load_rows_from_xlsx(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as zf:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"].lstrip("/") for rel in rels}

        sheet_target = None
        sheets = workbook.find("a:sheets", XLSX_NS)
        if sheets is None:
            raise ValueError("xlsx workbook missing sheets")
        for sheet in sheets:
            if sheet.attrib.get("name", "").strip().lower() == "details":
                rid = sheet.attrib[f"{{{REL_NS}}}id"]
                sheet_target = relmap[rid]
                break
        if sheet_target is None:
            first_sheet = next(iter(sheets))
            rid = first_sheet.attrib[f"{{{REL_NS}}}id"]
            sheet_target = relmap[rid]

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in sroot.findall("a:si", XLSX_NS):
                shared_strings.append("".join(t.text or "" for t in si.iterfind(".//a:t", XLSX_NS)))

        def cell_value(cell: ET.Element):
            ctype = cell.attrib.get("t")
            vnode = cell.find("a:v", XLSX_NS)
            if vnode is None:
                return None
            text = vnode.text
            if ctype == "s":
                return shared_strings[int(text)]
            if ctype == "b":
                return text == "1"
            return text

        root = ET.fromstring(zf.read(sheet_target))
        rows = root.findall(".//a:sheetData/a:row", XLSX_NS)
        if not rows:
            return []

        header_map: dict[int, str] = {}
        first_row = rows[0]
        for cell in first_row.findall("a:c", XLSX_NS):
            ref = cell.attrib.get("r", "")
            col = "".join(ch for ch in ref if ch.isalpha())
            if not col:
                continue
            header_map[_excel_col_index(col)] = str(cell_value(cell) or "").strip()

        rows_out: list[dict] = []
        for row in rows[1:]:
            values: dict[str, object] = {}
            for cell in row.findall("a:c", XLSX_NS):
                ref = cell.attrib.get("r", "")
                col = "".join(ch for ch in ref if ch.isalpha())
                if not col:
                    continue
                idx = _excel_col_index(col)
                values[header_map.get(idx, _excel_col_name(idx))] = cell_value(cell)
            if any(v not in (None, "") for v in values.values()):
                rows_out.append(_xlsx_row_to_analysis_row(values))
        return rows_out


def _xlsx_row_to_analysis_row(row: dict[str, object]) -> dict:
    bulletin_date = str(row.get("bulletin_date") or "")
    bulletin_status = str(row.get("bulletin_status") or "UNKNOWN")
    delta_file = _to_float(row.get("delta_file"))
    delta_signed = _to_float(row.get("delta_signed"))
    contract_month = str(row.get("contract_month") or "")
    option_type = str(row.get("option_type") or "").upper()
    product_code = str(row.get("product_code") or "OG")
    return {
        "source_file": str(row.get("source_file") or ""),
        "trade_date": bulletin_date,
        "report_date": bulletin_date,
        "product_code": product_code,
        "product_name": str(row.get("product_name") or ""),
        "expiry": contract_month,
        "option_type": option_type,
        "strike": _to_int(row.get("strike")),
        "settlement": _to_float(row.get("settle_price")),
        "delta": delta_signed if delta_signed is not None else delta_file,
        "delta_raw": delta_file,
        "open_interest": _to_int(row.get("open_interest")),
        "oi_change": _to_int(row.get("oi_change")),
        "total_volume": _to_int(row.get("total_volume")),
        "block_volume": 0,
        "pnt_volume": _to_int(row.get("pnt_volume")),
        "globex_volume": _to_int(row.get("globex_volume")),
        "outcry_volume": _to_int(row.get("open_outcry_volume")),
        "exercises": _to_int(row.get("exercises")),
        "pt_change": _to_float(row.get("price_change")),
        "source": bulletin_status,
    }



def _infer_forward_p0(raw_rows: list[dict], *, product: str, trade_date: str, expiries: list[str] | None) -> tuple[float | None, list[str]]:
    """Infer a P0 fallback from nearest-expiry call-put parity.

    This is not a live/open price. It is a structure reference price and is
    recorded as p0_source=forward_fallback.
    """
    try:
        from apps.features.options.black76 import infer_forward_price, sort_expiry_codes
        from apps.features.options.normalize import normalize_option_rows
    except Exception as exc:  # pragma: no cover - defensive CLI fallback
        return None, [f"forward_p0_import_failed:{exc}"]
    product_rows = [r for r in raw_rows if r.get("product_code", "") == product]
    normalized, _report = normalize_option_rows(
        product_rows,
        source="UNKNOWN",
        strike_min=2000,
        strike_max=12000,
        filter_strikes=True,
    )
    if expiries is not None:
        expiry_set = {e.upper() for e in expiries}
        normalized = [r for r in normalized if r.expiry.upper() in expiry_set]
    normalized = [r for r in normalized if r.trade_date == trade_date]
    active_expiries = sort_expiry_codes({r.expiry for r in normalized if r.expiry})
    if not active_expiries:
        return None, ["forward_p0_no_active_expiry"]
    f_value, warnings = infer_forward_price(normalized, trade_date, active_expiries[0])
    return f_value, [f"forward_p0_expiry:{active_expiries[0]}", *warnings]


def _resolve_analysis_expiries(args: argparse.Namespace, raw_rows: list[dict]) -> list[str] | None:
    if args.expiries:
        return [e.strip().upper() for e in args.expiries.split(",") if e.strip()]
    if args.all_expiries:
        return None
    from apps.features.options.black76 import sort_expiry_codes

    expiries = {
        str(row.get("expiry") or "").strip().upper()
        for row in raw_rows
        if str(row.get("product_code") or "") == args.product and str(row.get("trade_date") or "") == args.trade_date
    }
    selected = sort_expiry_codes(expiries)[:2]
    return selected or None


def _fetch_jin10_quote_p0(code: str, field: str) -> tuple[float | None, str | None, list[str]]:
    """Fetch a quote through a configured JSON-producing command."""
    configured_command = os.getenv("JIN10_QUOTE_COMMAND", "").strip()
    if not configured_command:
        return None, None, ["jin10_mcp_not_configured"]
    command = [*shlex.split(configured_command), code, field]
    try:
        proc = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=90,
        )
    except Exception as exc:
        return None, None, [f"jin10_mcp_exception:{type(exc).__name__}"]
    if proc.returncode != 0:
        return None, None, ["jin10_mcp_call_failed"]
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None, None, ["jin10_mcp_invalid_json"]
    if payload.get("error"):
        return None, None, [str(payload["error"])]
    try:
        value = float(payload.get("value"))
    except (TypeError, ValueError):
        return None, payload.get("time"), ["jin10_mcp_quote_value_missing"]
    warnings = [f"jin10_quote_code:{payload.get('code') or code}", f"jin10_quote_field:{field}"]
    if payload.get("name"):
        warnings.append(f"jin10_quote_name:{payload['name']}")
    return value, payload.get("time"), warnings


def _resolve_report_p0(args: argparse.Namespace, raw_rows: list[dict], expiries: list[str] | None) -> tuple[float | None, str, str | None, list[str]]:
    """Resolve end-of-day structure anchor.

    This is not the intraday price. Prefer manual same-day settlement, otherwise
    near-expiry parity-inferred F so Daily Bulletin data and structure anchor
    remain time-aligned.
    """
    if args.p0 is not None:
        return args.p0, "manual", None, []
    warnings: list[str] = []
    if args.p0_source == "jin10":
        warnings.append("deprecated_report_p0_jin10_ignored_use_live_p0_source")
    if args.p0_source in {"forward", "auto", "jin10"}:
        f_value, f_warnings = _infer_forward_p0(
            raw_rows,
            product=args.product,
            trade_date=args.trade_date,
            expiries=expiries,
        )
        warnings.extend(f_warnings)
        if f_value is not None:
            return float(f_value), "near_expiry_parity_fallback", None, warnings
    return None, "not_provided", None, warnings


def _resolve_live_p0(args: argparse.Namespace) -> tuple[float | None, str, str | None, list[str]]:
    """Resolve intraday/live price for strategy card only."""
    if args.live_p0 is not None:
        return args.live_p0, "manual", None, []
    source = args.live_p0_source
    # Backward compatibility: legacy --p0-source jin10 now maps to live_p0,
    # while report_p0 still falls back to near-expiry parity F.
    code = args.live_p0_code
    field = args.live_p0_field
    if args.p0_source == "jin10" and source == "none":
        source = "jin10"
        code = args.p0_code
        field = args.p0_field
    if source in {"jin10", "auto"}:
        quote_value, quote_time, quote_warnings = _fetch_jin10_quote_p0(code, field)
        if quote_value is not None:
            return quote_value, f"jin10_{field}", quote_time, quote_warnings
        return None, "not_provided", None, quote_warnings
    return None, "not_provided", None, []


def main() -> None:
    args = _parse_args()

    input_path = Path(args.parsed_json)
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        raw_rows = _load_rows(input_path)
    except Exception as exc:
        print(f"ERROR: unable to load input rows: {exc}", file=sys.stderr)
        sys.exit(1)

    expiries = _resolve_analysis_expiries(args, raw_rows)
    report_p0, report_p0_source, report_p0_timestamp, report_p0_warnings = _resolve_report_p0(args, raw_rows, expiries)
    live_p0, live_p0_source, live_p0_timestamp, live_p0_warnings = _resolve_live_p0(args)

    # Import and run analysis
    from apps.analysis.options.snapshot import build_options_snapshot, snapshot_to_dict
    from apps.analysis.options.agent_output import bind_options_snapshot_lineage, persist_options_agent_output
    from apps.analysis.options.report import render_options_report_markdown
    from apps.analysis.options.visual_report import build_options_visual_report_vm
    from apps.renderer.html.options_visual import render_options_visual_html

    result = build_options_snapshot(
        raw_rows,
        product=args.product,
        expiries=expiries,
        p0=report_p0,
        p0_source=report_p0_source,
        p0_timestamp=report_p0_timestamp,
        p0_warnings=report_p0_warnings,
        report_p0=report_p0,
        report_p0_source=report_p0_source,
        report_p0_timestamp=report_p0_timestamp,
        report_p0_warnings=report_p0_warnings,
        live_p0=live_p0,
        live_p0_source=live_p0_source,
        live_p0_timestamp=live_p0_timestamp,
        live_p0_warnings=live_p0_warnings,
        user_f=args.f,
        trade_date=args.trade_date,
        data_source_status=args.data_source_status or "UNKNOWN",
        data_source_url=args.data_source_url,
        strike_min=2000,
        strike_max=12000,
        filter_strikes=True,
        analysis_strike_min=args.analysis_strike_min,
        analysis_strike_max=args.analysis_strike_max,
        analysis_range_source="user_explicit" if args.analysis_strike_min is not None or args.analysis_strike_max is not None else None,
        analysis_range_mode=args.analysis_range_mode,
        analysis_range_sigma=args.analysis_range_sigma,
        analysis_range_min_half_width=args.analysis_range_min_half_width,
    )

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = Path("storage/outputs/cme_options") / args.trade_date
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot_dict = bind_options_snapshot_lineage(snapshot_to_dict(result), run_id=args.run_id)
    json_path = out_dir / "options_analysis.json"
    json_path.write_text(
        json.dumps(snapshot_dict, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"JSON snapshot written: {json_path}")

    md_content = render_options_report_markdown(result)
    md_path = out_dir / "options_analysis.md"
    md_path.write_text(md_content, encoding="utf-8")
    print(f"Markdown report written: {md_path}")

    visual_vm = build_options_visual_report_vm(result)
    visual_json_path = out_dir / "options_visual_report.json"
    visual_json_path.write_text(
        json.dumps(visual_vm.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Visual JSON written: {visual_json_path}")

    visual_html_path = out_dir / "options_visual_report.html"
    visual_html_path.write_text(
        render_options_visual_html(visual_vm),
        encoding="utf-8",
    )
    print(f"Visual HTML written: {visual_html_path}")

    persisted_agent_output = persist_options_agent_output(
        snapshot_dict,
        artifact_dir=out_dir,
        run_id=str(snapshot_dict["run_id"]),
    )
    print(f"Agent output persisted: {persisted_agent_output['agent_output_id']}")

    print("\n=== Analysis Summary ===")
    print(f"Trade date: {result.trade_date}")
    print(f"Product: {result.product}")
    print(f"Expiries: {', '.join(result.expiries)}")
    print(f"Rows: {len(result.normalized_rows)}")
    print(f"Forward price: {result.forward_price} ({result.f_source})")
    print(f"Report P0: {result.report_p0} ({result.report_p0_source})")
    print(f"Live P0: {result.live_p0} ({result.live_p0_source})")
    print(f"Gamma Zero: {result.netgex.gamma_zero}")
    print(f"Used real GEX: {result.used_real_gex}")
    print(f"Walls identified: {len(result.scored_walls)}")
    print(f"Roll signals: {len(result.roll_signals)}")
    print(f"Intent: {result.intent.primary_intent.intent_type.value} (score={result.intent.primary_intent.score:.2f})")
    print(f"Data quality warnings: {len(result.data_quality.warnings)}")
    print(f"Persisted agent output: {persisted_agent_output}")


if __name__ == "__main__":
    main()
