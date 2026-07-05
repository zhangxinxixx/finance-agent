from __future__ import annotations

from dataclasses import asdict, dataclass

from apps.features.macro.snapshot import MacroSnapshot


@dataclass(frozen=True)
class MacroRisk:
    title: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class MacroConclusion:
    as_of: str
    bias: str
    state: str
    quantity_layer: str
    price_layer: str
    dollar_layer: str
    action: str
    action_priority: str
    no_go_actions: list[str]
    trigger_upgrade: list[str]
    trigger_downgrade: list[str]
    risks: list[MacroRisk]
    reasoning: str
    missing_inputs: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "bias": self.bias,
            "state": self.state,
            "quantity_layer": self.quantity_layer,
            "price_layer": self.price_layer,
            "dollar_layer": self.dollar_layer,
            "action": self.action,
            "action_priority": self.action_priority,
            "no_go_actions": self.no_go_actions,
            "trigger_upgrade": self.trigger_upgrade,
            "trigger_downgrade": self.trigger_downgrade,
            "risks": [risk.to_dict() for risk in self.risks],
            "reasoning": self.reasoning,
            "missing_inputs": self.missing_inputs,
        }


def build_macro_conclusion(snapshot: MacroSnapshot) -> MacroConclusion:
    ind = snapshot.indicators
    missing_inputs = _missing_required_inputs(ind)
    quantity_layer = _quantity_layer(ind)
    price_layer = _price_layer(ind)
    dollar_layer = _dollar_layer(ind)
    real_layer = _real_rate_layer(ind)
    supportive = sum(layer in {"偏松", "顺风", "中期缓和", "宽松"} for layer in (quantity_layer, price_layer, dollar_layer, real_layer))
    restrictive = sum(layer in {"偏紧", "分裂偏紧", "逆风", "重新压制", "高位压制", "钱仍贵"} for layer in (quantity_layer, price_layer, dollar_layer, real_layer))
    if supportive >= 2 and restrictive == 0:
        bias = "中性偏多"
    elif restrictive >= 2 and supportive == 0:
        bias = "中性偏空"
    elif supportive > restrictive:
        bias = "中性偏多"
    elif restrictive > supportive:
        bias = "中性偏空"
    else:
        bias = "中性"
    us10y = ind.get("US10Y")
    if us10y and us10y.value >= 4.7 and dollar_layer == "逆风" and real_layer in {"重新压制", "高位压制"}:
        state = "流动性踩踏态"
    elif real_layer in {"重新压制", "高位压制"} and dollar_layer == "逆风":
        state = "利率压制态"
    elif quantity_layer == "偏松" and dollar_layer == "顺风" and price_layer in {"中性", "宽松"}:
        state = "趋势顺风态"
    elif quantity_layer == "偏松" and dollar_layer == "顺风":
        state = "过渡释放态"
    else:
        state = "过渡释放态"
    if state == "趋势顺风态":
        action = "回踩接多 / 突破跟随"
        action_priority = "主要"
    elif state == "过渡释放态" and bias in {"中性偏多", "偏多"}:
        action = "回踩接多 / 等待"
        action_priority = "回踩接多优先，其次等待"
    elif state == "利率压制态":
        action = "反弹空 / 等待"
        action_priority = "等待反弹空 / 等确认"
    elif state == "流动性踩踏态":
        action = "防踩踏 / 等待"
        action_priority = "降低主动方向判断"
    else:
        action = "等待"
        action_priority = "主要"
    risks = _risks(ind)
    reasoning = _reasoning(ind, bias=bias, state=state, quantity_layer=quantity_layer, price_layer=price_layer, dollar_layer=dollar_layer, real_layer=real_layer)
    return MacroConclusion(
        as_of=snapshot.as_of, bias=bias, state=state, quantity_layer=quantity_layer,
        price_layer=price_layer, dollar_layer=dollar_layer, action=action,
        action_priority=action_priority,
        no_go_actions=[
            "不建议在当前环境里直接追高",
            "不在 DXY 101 上方直接追多",
            "不把单日反弹当趋势反转",
            "不在实际利率仍高时重仓抄底",
            "不在急跌后追空，除非 DXY 和实际利率继续上冲",
        ],
        trigger_upgrade=[
            "DXY 跌破 100.8",
            "US10Y 跌破 4.35%",
            "10Y 实际利率跌回 2.10% 下方",
            "T10YIE 不再继续快速下行",
            "ETF / GLD 停止流出或开始回流",
        ],
        trigger_downgrade=[
            "DXY 重新上破 101.8",
            "US10Y 回到 4.50% 上方",
            "10Y 实际利率重新站上 2.20%",
            "US02Y 重回 4.20% 上方",
            "TGA 回升 + 准备金继续下降",
        ],
        risks=risks, reasoning=reasoning, missing_inputs=missing_inputs,
    )


def _missing_required_inputs(indicators):
    required = ["ON_RRP_USAGE", "TGA", "RESERVES", "SOFR", "EFFR", "IORB", "US02Y", "US10Y", "BREAKEVEN_10Y", "REAL_10Y", "DXY"]
    return [s for s in required if s not in indicators]


def _quantity_layer(ind):
    rrp, tga, reserves = ind.get("ON_RRP_USAGE"), ind.get("TGA"), ind.get("RESERVES")
    rrp_rising_from_low = rrp and rrp.value < 10 and (rrp.weekly_change or 0) > 5
    tga_releasing = tga and tga.weekly_change is not None and tga.weekly_change < -25
    tga_absorbing = tga and tga.weekly_change is not None and tga.weekly_change > 50
    reserves_falling = reserves and reserves.weekly_change is not None and reserves.weekly_change < -25
    reserves_rising = reserves and reserves.weekly_change is not None and reserves.weekly_change > 25

    if tga_releasing and reserves_falling:
        return "分裂偏紧"
    if (rrp_rising_from_low or tga_absorbing) and reserves_falling:
        return "偏紧"
    if tga_releasing and reserves_rising:
        return "偏松"

    score = 0
    if rrp and rrp.value < 50:
        score += 1
    if tga and (tga.weekly_change is not None and tga.weekly_change < -25):
        score += 1
    if reserves and (reserves.weekly_change is not None and reserves.weekly_change > 25):
        score += 1
    if tga and reserves and (tga.weekly_change or 0) > 50 and (reserves.weekly_change or 0) < -25:
        score -= 2
    if score >= 2:
        return "偏松"
    if score <= -1:
        return "偏紧"
    return "中性"


def _price_layer(ind):
    sofr, effr, iorb, us02y = ind.get("SOFR"), ind.get("EFFR"), ind.get("IORB"), ind.get("US02Y")
    high_count = sum(v is not None and v.value >= threshold for v, threshold in ((sofr, 3.5), (effr, 3.5), (iorb, 3.5), (us02y, 3.8)))
    easing_count = sum(v is not None and v.weekly_change is not None and v.weekly_change < -0.02 for v in (sofr, effr, iorb, us02y))
    if high_count >= 3:
        return "钱仍贵"
    if easing_count >= 2:
        return "宽松"
    return "中性"


def _dollar_layer(ind):
    dxy = ind.get("DXY")
    if not dxy:
        return "中性"
    if dxy.value >= 101:
        return "逆风"
    if dxy.value < 98 and ((dxy.weekly_change or 0) < 0 or (dxy.monthly_change or 0) < 0):
        return "顺风"
    if dxy.value >= 99 and ((dxy.weekly_change or 0) > 0 or (dxy.monthly_change or 0) > 0):
        return "逆风"
    return "中性"


def _real_rate_layer(ind):
    real_10y = ind.get("REAL_10Y")
    if not real_10y:
        return "中性"
    if real_10y.value >= 2.1:
        return "高位压制"
    if (real_10y.monthly_change is not None and real_10y.monthly_change < -0.03) or real_10y.value < 1.9:
        return "中期缓和"
    if real_10y.value > 1.95 and (real_10y.weekly_change or 0) > 0:
        return "重新压制"
    return "中性"


def _risks(ind):
    return [
        MacroRisk("DXY 重新上破 101.8", "这会直接强化美元逆风，黄金反弹更容易被压回。"),
        MacroRisk("10Y 实际利率重新站上 2.20%", "这是黄金最核心的机会成本变量，一旦回升，上涨更容易被重新定义成修复而不是转势。"),
        MacroRisk("US02Y 再次变鹰", "2Y 仍在高位，只要短端机会成本不继续回落，黄金日内延续性就容易打折。"),
        MacroRisk("TGA 再次上升 + 准备金回落", "这意味着数量层会从当前分裂偏紧进一步转向偏紧。"),
        MacroRisk("Breakeven 下行快于名义利率", "这会被动抬升真实利率，对黄金比单纯名义利率上行更伤。"),
    ]


def _fmt_signed(value: float | None, *, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "暂无"
    return f"{value:+.{digits}f}{suffix}"


def _reasoning(ind, *, bias, state, quantity_layer, price_layer, dollar_layer, real_layer):
    tga, reserves = ind.get("TGA"), ind.get("RESERVES")
    real_10y, dxy = ind.get("REAL_10Y"), ind.get("DXY")
    parts = [f"综合判断为{bias}，当前更接近{state}。", f"数量层为{quantity_layer}，价格层为{price_layer}，美元层为{dollar_layer}，实际利率层为{real_layer}。"]
    if tga and reserves:
        if (tga.weekly_change or 0) < 0 and (reserves.weekly_change or 0) < 0:
            quantity_sentence = "短线财政释放与准备金回落并存，数量层分裂偏紧。"
        elif (tga.weekly_change or 0) < 0:
            quantity_sentence = "财政抽水缓和，数量层边际偏释放。"
        elif (reserves.weekly_change or 0) < 0:
            quantity_sentence = "准备金回落，数量层边际偏紧。"
        else:
            quantity_sentence = "数量层暂未形成单边信号。"
        parts.append(f"TGA 周变化 {_fmt_signed(tga.weekly_change, digits=3, suffix='B')}，准备金周变化 {_fmt_signed(reserves.weekly_change, digits=3, suffix='B')}，{quantity_sentence}")
    if real_10y:
        if real_layer == "中期缓和":
            real_sentence = "机会成本中期缓和但绝对水平仍不低。"
        elif real_layer == "重新压制":
            real_sentence = "机会成本重新压制黄金。"
        elif real_layer == "高位压制":
            real_sentence = "机会成本仍高位压制黄金。"
        else:
            real_sentence = "机会成本方向暂按中性处理。"
        parts.append(f"10Y 实际利率约 {real_10y.value:.2f}%，月变化 {_fmt_signed(real_10y.monthly_change, suffix='%')}，{real_sentence}")
    if dxy:
        if dollar_layer == "顺风":
            dollar_sentence = "美元对黄金形成顺风。"
        elif dollar_layer == "逆风":
            dollar_sentence = "美元对黄金形成逆风。"
        else:
            dollar_sentence = "美元影响暂按中性处理。"
        parts.append(f"DXY 当前 {dxy.value:.3f}，周/月变化分别为 {_fmt_signed(dxy.weekly_change)} / {_fmt_signed(dxy.monthly_change)}，{dollar_sentence}")
    return "".join(parts)
