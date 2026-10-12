"""Visible macro evidence so a fluent narrative cannot hide missing layers."""


def macro_causal_section(causal):
    engines = causal["engines"]
    parts = [
        "L0事实 → L1动能与结构 → L2市场预期 → L3政策反应假设 → L4传导 → L5叙事 → L6黄金验证。计算不等于已识别因果；缺失不能填成中性。",
        "### 通胀动能（系统按指数计算，%）",
        "以下精确值不是官方新闻稿的发布舍入值；官方发布值需独立来源，不把计算结果冒充发布值。",
        "| 序列 | 观察月 | MoM | YoY及口径 | 3M SAAR | 6M SAAR | 状态 |",
        "|---|---|---:|---|---:|---:|---|",
    ]

    def val(v):
        return "缺失" if v is None else f"{v:.2f}"

    for name, r in engines["inflation"].get("series", {}).items():
        parts.append(
            f"| {name} | {r.get('observation_date', '缺失')} | {val(r.get('mom_pct'))} | {val(r.get('yoy_pct'))} / {r.get('yoy_basis', '未知')} | {val(r.get('saar_3m_pct'))} | {val(r.get('saar_6m_pct'))} | {r['status']} |"
        )
    if not engines["inflation"].get("series"):
        parts.append("通胀特征未采集，不能用指数水平代替通胀率。")
    parts.extend(
        [
            "",
            "### 国债分解（bp）",
            "| 窗口 | 名义10Y变化 | 实际10Y变化 | BE变化 | 恒等式残差 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, r in engines["treasury"]["windows"].items():
        parts.append(
            "| "
            + name
            + " | "
            + " | ".join(val(r.get(k)) for k in ["nominal_bp", "real_bp", "breakeven_bp", "identity_residual_bp"])
            + " |"
        )
    policy = engines["policy"]
    from apps.renderer.markdown.research_evidence import policy_path_table
    parts += [
        "",
        "### 政策路径与因果缺口",
        f"政策分布：{policy['status']}；{policy.get('reason') or '目标区间中点期望，不等于EFFR'}。",
    ]
    for m in policy["meetings"]:
        parts.append(
            f"- {m['meeting_date']}：期望中点{m['expected_target_midpoint_pct']:.3f}%，分布标准差{m['distribution_sd_bp']:.1f}bp；1D重定价{val(m['repricing_1d_bp'])}bp，1W {val(m['repricing_1w_bp'])}bp。"
        )
    if policy.get('policy_path'):
        parts.append(policy_path_table(policy))
    parts += [
        "期限溢价/拍卖归因："
        + engines["treasury"]["term_premium"]["reason"]
        + "；"
        + engines["treasury"]["auction_supply"]["reason"]
        + "。",
        "残差需求：" + engines["residual"]["reason"] + "；不把未解释涨幅认定为央行或OTC买盘。",
        "### 总Agent必须回答的研究问题",
    ]
    parts.extend("- " + q["question"] for q in causal["questions"])
    parts.append("上述问题由下方模型正文回答；没有证据必须说明未确认。ETF/CFTC/CME/PA用于验证，不替代宏观解释。")
    return {
        "section_id": "macro_causal",
        "title": "宏观因果分析：通胀、Fed与国债",
        "body": "\n".join(parts),
        "status": "partial",
        "source_refs": causal["source_refs"],
        "data_category": "deterministic_calculation",
    }
