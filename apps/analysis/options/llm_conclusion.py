"""LLM-generated analytical conclusions for CME gold options reports.

Consumes structured options_analysis JSON (read-only), produces a full Chinese
Markdown report. This is a SEPARATE post-processing step, NOT embedded in the
main pipeline.

Architecture:
  features (deterministic) → analysis → renderer → output (.md/.json)
                                                    ↓
  llm_conclusion.py ← fixed-role Agent (GPT-5.5) ← snapshot JSON
                                                    ↓
  enhance_options_report.py → writes agent markdown into enhanced report
"""

from __future__ import annotations

from typing import Any


def build_conclusion_prompt(snapshot: dict[str, Any]) -> str:
    """Build a structured Chinese prompt from the options analysis snapshot.

    The agent must output Markdown only, not JSON.
    """
    data_source = snapshot.get("data_source", {}) or {}
    parameters = snapshot.get("parameters", {}) or {}
    gex = snapshot.get("gex", {}) or {}
    gex_by_expiry = gex.get("by_expiry", {}) or {}
    netgex_aggregate = gex.get("netgex_aggregate", {}) or {}
    gamma_zero_payload = netgex_aggregate.get("gamma_zero", {}) or {}
    exposure = snapshot.get("exposure", {}) or {}
    exposure_by_expiry = exposure.get("by_expiry", {}) or {}
    normalization = snapshot.get("normalization", {}) or {}

    trade_date = snapshot.get("trade_date", "")
    product = snapshot.get("product") or snapshot.get("product_code") or data_source.get("product") or data_source.get("product_code") or "OG"
    expiries = snapshot.get("expiries") or list(gex_by_expiry.keys())
    p0 = snapshot.get("p0", parameters.get("p0"))
    source_status = snapshot.get("data_source_status") or data_source.get("status") or data_source.get("version_type") or "UNKNOWN"
    source_url = snapshot.get("data_source_url") or data_source.get("url") or data_source.get("source_url") or data_source.get("raw_path")
    used_real_gex = snapshot.get("used_real_gex", parameters.get("used_real_gex"))
    f_source = snapshot.get("f_source") or parameters.get("f_source", "")
    forward_price = snapshot.get("forward_price", parameters.get("f_value"))
    netgex = snapshot.get("netgex") or {
        "gamma_zero": gamma_zero_payload.get("price"),
        "gamma_zero_method": gamma_zero_payload.get("method"),
        "warnings": netgex_aggregate.get("warnings", []),
    }
    gex_summary_by_expiry = snapshot.get("gex_summary_by_expiry") or {
        expiry: payload.get("summary", {}) for expiry, payload in gex_by_expiry.items()
    }
    gex_top_by_expiry = snapshot.get("gex_top_by_expiry") or {
        expiry: payload.get("gex_top", []) for expiry, payload in gex_by_expiry.items()
    }
    exposure_summary_by_expiry = snapshot.get("exposure_summary_by_expiry") or {
        expiry: payload.get("summary", payload) for expiry, payload in exposure_by_expiry.items()
    }
    iv_skew_by_expiry = snapshot.get("iv_skew_by_expiry") or {
        expiry: payload.get("iv_skew", {}) for expiry, payload in gex_by_expiry.items()
    }
    scored_walls = snapshot.get("scored_walls", [])
    wall_scores = snapshot.get("wall_scores", [])
    roll_signals = snapshot.get("roll_signals", [])
    intent = snapshot.get("intent", {})
    data_quality = _normalize_data_quality(snapshot.get("data_quality", {}) or {})
    calibration = snapshot.get("calibration", {})
    audit = snapshot.get("audit", {}) or {}
    forward_warnings = snapshot.get("forward_warnings") or [
        warning
        for payload in parameters.get("forward_by_expiry", {}).values()
        for warning in payload.get("warnings", [])
    ]
    expiry_warnings = snapshot.get("expiry_warnings", [])
    norm_report = snapshot.get("norm_report") or normalization

    near_month = expiries[0] if len(expiries) > 0 else None
    next_month = expiries[1] if len(expiries) > 1 else None

    def _fmt_num(value: Any, decimals: int = 2) -> str:
        if isinstance(value, (int, float)):
            if abs(value) >= 1e9:
                return f"{value / 1e9:.{decimals}f}B"
            if abs(value) >= 1e6:
                return f"{value / 1e6:.{decimals}f}M"
            if abs(value) >= 1e3:
                return f"{value / 1e3:.{decimals}f}K"
            return f"{value:.{decimals}f}"
        return str(value if value is not None else "N/A")

    def _fmt_pct(value: Any, decimals: int = 2) -> str:
        if isinstance(value, (int, float)):
            return f"{value * 100:.{decimals}f}%"
        return "N/A"

    prompt = f"""你是一位专业 CME / COMEX 黄金期权结构分析师。
请基于以下结构化快照，直接输出一份完整、可发布的中文 Markdown 分析报告。

硬性要求：
1. 只输出 Markdown 正文，不要 JSON，不要代码块说明，不要解释分析过程。
2. 程序只负责计算，你只负责写报告。
3. 至少比较两个到期月：近月 {near_month or 'N/A'} vs 次月 {next_month or 'N/A'}。
4. 风格要接近专业实盘复盘：一句话结论先行，随后给出数据口径、双月对比、GEX、墙位、Gamma Zero、IV Skew、Roll、机构意图、支撑阻力、策略框架、改判开关、数据质量。
5. 如果数据是 PRELIM，要明确提示最终数据可能修正。
6. 不得编造任何没给出的持仓、成交、IV 或价格。
7. 术语优先使用中文，保留必要英文缩写：GEX、Gamma Zero、WallScore、PNT、OI、IV、Skew。

=== 结构化快照 ===
交易日期: {trade_date}
产品: {product}
数据状态: {source_status}
数据来源: {source_url or 'N/A'}
当前价 P0: {p0}
Forward price: {forward_price} ({f_source})
是否使用真实 GEX: {used_real_gex}
分析月份: {', '.join(expiries) if expiries else 'N/A'}
近月 / 次月: {near_month or 'N/A'} / {next_month or 'N/A'}

Norm report:
- total_input_rows: {norm_report.get('total_input_rows', 'N/A')}
- duplicates_merged: {norm_report.get('duplicates_merged', 'N/A')}
- rows_missing_settlement: {norm_report.get('rows_missing_settlement', 'N/A')}
- rows_missing_delta: {norm_report.get('rows_missing_delta', 'N/A')}
- rows_filtered_by_strike: {norm_report.get('rows_filtered_by_strike', 'N/A')}

Data quality:
- zero_oi_count: {data_quality.get('zero_oi_count', 'N/A')}
- low_oi_count: {data_quality.get('low_oi_count', 'N/A')}
- proxy_strike_count: {data_quality.get('proxy_strike_count', 'N/A')}
- prelim_data_count: {data_quality.get('prelim_data_count', 'N/A')}
- warnings: {data_quality.get('warnings', [])}

Forward warnings: {forward_warnings}
Expiry warnings: {expiry_warnings}

NetGEX aggregate:
- gamma_zero: {netgex.get('gamma_zero', 'N/A')}
- gamma_zero_method: {netgex.get('gamma_zero_method', 'N/A')}
- warnings: {netgex.get('warnings', [])}

Primary intent:
- primary_type: {intent.get('primary_intent', {}).get('intent_type', intent.get('type', 'N/A'))}
- score: {intent.get('primary_intent', {}).get('score', intent.get('score', 'N/A'))}
- confidence: {intent.get('primary_intent', {}).get('confidence', intent.get('confidence', 'N/A'))}
- evidence: {intent.get('primary_intent', {}).get('evidence', intent.get('evidence', []))}
- all_scores: {intent.get('all_scores', {})}

Roll signals: {roll_signals}
Calibration: {calibration}

Audit fields:
- data_audit: {audit.get('data_audit', {})}
- black76_audit: {audit.get('black76_audit', {})}
- gex_audit: {audit.get('gex_audit', {})}
- wallscore_audit: {audit.get('wallscore_audit', {})}
- intent_audit: {audit.get('intent_audit', {})}

=== 近月 / 次月关键摘要 ===
近月 summary: {gex_summary_by_expiry.get(near_month, {}) if near_month else {}}
次月 summary: {gex_summary_by_expiry.get(next_month, {}) if next_month else {}}

近月 top GEX: {gex_top_by_expiry.get(near_month, [])[:5] if near_month else []}
次月 top GEX: {gex_top_by_expiry.get(next_month, [])[:5] if next_month else []}

近月 exposure summary: {exposure_summary_by_expiry.get(near_month, {}) if near_month else {}}
次月 exposure summary: {exposure_summary_by_expiry.get(next_month, {}) if next_month else {}}

近月 IV skew: {iv_skew_by_expiry.get(near_month, {}) if near_month else {}}
次月 IV skew: {iv_skew_by_expiry.get(next_month, {}) if next_month else {}}

Top walls（按已排序结果前 15 条）：
{scored_walls[:15] if scored_walls else wall_scores[:15]}

=== 输出结构建议 ===
请按以下章节顺序输出，并写成真正的分析稿，而不是模板填空：

# CME 黄金期权结构分析报告 — {trade_date}

## 数据声明
## 一句话结论
## 数据口径
## 近月 / 次月对比
## 核心 GEX 结果
## 重点墙位
## Gamma Zero / 分水岭
## IV Smile / Skew
## Roll / 换月迁移
## 机构意图（I1–I4）
## 支撑 / 阻力地图
## 实盘策略框架
## 改判开关
## 数据质量与局限性

=== 写作风格要求 ===
- 语气要像专业黄金期权分析师的成稿。
- 结论先行，解释后置。
- 尽量使用这类表达：最强防守地板、最强真实 GEX 磁吸位、方向分水岭、主战区、库存墙、再平衡、不是趋势确认。
- 如果结构偏防守但仍有上方弹性，要明确写"不是趋势确认"。
- 站稳 4600 只能写成进入 Call-GEX 更占优结构区，仍需 4650/4700 接受确认，不能单独视为趋势启动。
- 必须说明 Gamma Zero 仅基于 Black-76 可估值行，Proxy 行不参与零轴拟合。
- 必须说明 WallScore 的 GEX/OI/ΔOI/Volume/Block-PNT/Distance 分项公式。
- 如果近月和次月出现分歧，要强调迁移、分层、接力。
- 如果 PRELIM 数据存在，务必在开头或数据口径中说明风险。

=== 硬性工程字段要求（每版必写，不可省略） ===
1. 数据口径章必须包含全链审计表：product_rows / valid_rows / analysis_range / range_rows / excluded_outside_analysis_range / full_chain_filter_excluded / rows_missing_settlement / rows_missing_delta / black76_rows / proxy_rows / proxy_gex_share。必须写 gamma_zero_proxy_included=false。
2. 各到期月参数表必须包含：trade_date / expiry_date / T / F / F_source / F_pairs_used / D。
3. WallScore 表必须包含 dominant_side 和 wall_role 两列（来自快照中的 dominant_side 字段）。
4. Gamma Zero 章必须写明 cross_month_reference_price 和 report_p0_source，不能只拿 JUN F 近似。
5. 机构意图章必须输出 I1/I2/I3/I4 各意图的分数表。意图标签优先写 "I2 防守型再平衡，向 I1 迁移"（从快照 intent_audit.wording 取），不要自己改写为"偏 I1"或"纯防守"。
6. 无 live_p0 时必须写明"以下为日终结构剧本，实际使用前需用 live_p0 重新排序上下支撑阻力"。
7. 如有前后日对比（较上一日变化），必须写明 comparison_baseline：同程序版本、同 analysis_range、同 Black-76 口径、同 gex_scope=main_range、proxy_included_in_zero=false。

只输出最终 Markdown 正文，不要额外说明。"""
    return prompt



def _normalize_data_quality(data_quality: dict[str, Any]) -> dict[str, Any]:
    categories = data_quality.get("categories", {}) if isinstance(data_quality, dict) else {}
    if not categories:
        return data_quality
    normalized = dict(data_quality)
    normalized.setdefault("zero_oi_count", categories.get("zero_oi"))
    normalized.setdefault("low_oi_count", categories.get("low_oi"))
    normalized.setdefault("proxy_strike_count", categories.get("proxy_strikes"))
    normalized.setdefault("prelim_data_count", categories.get("prelim_data"))
    normalized.setdefault("rows_missing_settlement", categories.get("rows_missing_settlement"))
    normalized.setdefault("rows_missing_delta", categories.get("rows_missing_delta"))
    normalized.setdefault("rows_filtered_by_strike", categories.get("rows_filtered_by_strike"))
    normalized.setdefault("duplicates_merged", categories.get("duplicates_merged"))
    return normalized

def parse_llm_response(text: str) -> str:
    """Return raw Markdown response from the agent.

    The agent is expected to output Markdown directly. This helper only trims
    surrounding whitespace and strips code fences if the model added them.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
        else:
            text = "\n".join(lines[1:])
    return text.strip()


# ── LLM-powered conclusion ──────────────────────────────────────


def invoke_options_llm(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Call LLM with options analysis snapshot, return structured result.

    Returns dict with keys:
        - markdown: str (full LLM markdown report)
        - one_line_conclusion: str
        - model: str
        - provider: str
        - latency_ms: int
        - tokens: dict
    """
    from apps.llm.gateway import chat_sync

    prompt = build_conclusion_prompt(snapshot)

    response = chat_sync(
        messages=[
            {
                "role": "system",
                "content": "你是一位专业 CME / COMEX 黄金期权结构分析师。只输出 Markdown 正文。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
    )

    markdown = parse_llm_response(response.content)

    # Extract one-line conclusion
    import re
    conclusion_match = re.search(
        r"##\s*一句话结论\s*\n(.+?)(?=\n##|\Z)", markdown, re.DOTALL
    )
    one_line = conclusion_match.group(1).strip() if conclusion_match else ""

    return {
        "markdown": markdown,
        "one_line_conclusion": one_line,
        "model": response.model,
        "provider": response.provider,
        "latency_ms": response.latency_ms,
        "tokens": response.usage,
    }
