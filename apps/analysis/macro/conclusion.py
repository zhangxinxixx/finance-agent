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
    supportive = sum(layer in {"偏松", "顺风", "中期缓和"} for layer in (quantity_layer, dollar_layer, real_layer))
    restrictive = sum(layer in {"偏紧", "逆风", "重新压制"} for layer in (quantity_layer, dollar_layer, real_layer))
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
    if quantity_layer == "偏松" and dollar_layer == "顺风" and price_layer == "钱仍贵":
        state = "状态 2 —— 过渡释放态"
    elif quantity_layer == "偏松" and dollar_layer == "顺风" and price_layer in {"中性", "宽松"}:
        state = "状态 1 —— 趋势顺风态"
    elif price_layer == "钱仍贵" and dollar_layer == "逆风":
        state = "状态 3 —— 利率压制态"
    else:
        state = "状态 2 —— 过渡释放态"
    if state.startswith("状态 1"):
        action = "回踩接多"
        action_priority = "主要"
    elif state.startswith("状态 2") and bias in {"中性偏多", "偏多"}:
        action = "回踩接多 / 等待"
        action_priority = "回踩接多优先，其次等待"
    elif state.startswith("状态 3"):
        action = "反弹空 / 等待"
        action_priority = "防守优先"
    else:
        action = "等待"
        action_priority = "主要"
    risks = _risks(ind)
    reasoning = _reasoning(ind, bias=bias, state=state, quantity_layer=quantity_layer, price_layer=price_layer, dollar_layer=dollar_layer, real_layer=real_layer)
    return MacroConclusion(
        as_of=snapshot.as_of, bias=bias, state=state, quantity_layer=quantity_layer,
        price_layer=price_layer, dollar_layer=dollar_layer, action=action,
        action_priority=action_priority,
        no_go_actions=["不建议在当前环境里直接追高", "不建议在 DXY 已转弱、数量层已偏松的情况下机械追空"],
        trigger_upgrade=["DXY 继续维持在 98 下方偏弱", "10Y 实际利率继续向 1.85%—1.90% 区间回落", "US02Y 不重新站回 3.90% 上方"],
        trigger_downgrade=["DXY 重新反抽回 99 上方", "10Y 实际利率回到 1.95% 上方", "TGA 再度明显回升且准备金回落"],
        risks=risks, reasoning=reasoning, missing_inputs=missing_inputs,
    )


def _missing_required_inputs(indicators):
    required = ["ON_RRP_USAGE", "TGA", "RESERVES", "SOFR", "EFFR", "IORB", "US02Y", "US10Y", "BREAKEVEN_10Y", "REAL_10Y", "DXY"]
    return [s for s in required if s not in indicators]


def _quantity_layer(ind):
    rrp, tga, reserves = ind.get("ON_RRP_USAGE"), ind.get("TGA"), ind.get("RESERVES")
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
    if dxy.value < 98 and ((dxy.weekly_change or 0) < 0 or (dxy.monthly_change or 0) < 0):
        return "顺风"
    if dxy.value >= 99 and ((dxy.weekly_change or 0) > 0 or (dxy.monthly_change or 0) > 0):
        return "逆风"
    return "中性"


def _real_rate_layer(ind):
    real_10y = ind.get("REAL_10Y")
    if not real_10y:
        return "中性"
    if (real_10y.monthly_change is not None and real_10y.monthly_change < -0.03) or real_10y.value < 1.9:
        return "中期缓和"
    if real_10y.value > 1.95 and (real_10y.weekly_change or 0) > 0:
        return "重新压制"
    return "中性"


def _risks(ind):
    return [
        MacroRisk("DXY 重新反抽并站回 99—100 区域", "这会直接削弱当前黄金最明确的顺风项。"),
        MacroRisk("10Y 实际利率重新回到 1.95% 上方", "这是黄金最核心的机会成本变量，一旦回升，上涨更容易被重新定义成修复而不是转势。"),
        MacroRisk("US02Y 再次变鹰", "2Y 仍在高位，只要短端机会成本不继续回落，黄金日内延续性就容易打折。"),
        MacroRisk("TGA 再次上升 + 准备金回落", "这意味着数量层会从现在的偏松切回偏紧。"),
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
        parts.append(f"TGA 周变化 {_fmt_signed(tga.weekly_change, digits=3, suffix='B')}，准备金周变化 {_fmt_signed(reserves.weekly_change, digits=3, suffix='B')}，说明数量层边际更偏向释放。")
    if real_10y:
        parts.append(f"10Y 实际利率约 {real_10y.value:.2f}%，月变化 {_fmt_signed(real_10y.monthly_change, suffix='%')}，机会成本中期缓和但绝对水平仍不低。")
    if dxy:
        parts.append(f"DXY 当前 {dxy.value:.3f}，周/月变化分别为 {_fmt_signed(dxy.weekly_change)} / {_fmt_signed(dxy.monthly_change)}，美元对黄金形成顺风。")
    return "".join(parts)
