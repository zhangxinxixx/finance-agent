import type { SignalDirection } from "@/types/dashboard";

export function directionLabel(direction: SignalDirection) {
  if (direction === "bullish") return "偏多";
  if (direction === "bearish") return "偏空";
  return "中性";
}

// 后端英文 -> 中文翻译（覆盖综合判断卡所有字段）
export function translateText(text: string): string {
  if (!text) return "—";

  const exact: Record<string, string> = {
    neutral: "中性",
    bullish: "偏多",
    bearish: "偏空",
    mixed: "混合",
    "neutral-bullish": "中性偏多",
    "neutral-bearish": "中性偏空",
    "USD/oz": "美元/盎司",
    "options: PRELIM only (FINAL unavailable)": "期权数据：初稿（终稿未出）",
    "macro: partial (1 symbols unavailable)": "宏观数据：部分缺失",
    "tasks: no recent task history": "暂无任务记录",
    "CME data source: PRELIM (FINAL preferred)": "CME数据：初步数据（建议使用最终数据）",
    "Data source openbb_macro: not_connected": "OpenBB宏观数据：未连接",
    "Data source bls_calendar: not_connected": "BLS日历：未连接",
    macro_latest: "宏观最新快照",
    "CME GC forward / latest available": "CME黄金期货 / 最新可用",
    "macro easing": "宏观宽松",
    "macro tightening": "宏观紧缩",
    "neutral/stagflation": "中性/滞胀",
    "risk-on": "风险偏好",
    "risk-off": "风险规避",
    "transition relief": "过渡释放态",
    "weak repair": "弱修复",
    "Summary Only": "仅摘要",
    "DAILY COMPOSITE": "综合分析",
    "I1_defensive": "一级防御",
    "OpenBB Macro/Market": "OpenBB 宏观/市场",
  };

  if (exact[text]) return exact[text];

  const prefixesToStrip = [
    "macro as_of ",
    "macro prior invalid condition: ",
    "options prior invalid condition: ",
    "risk prior invalid condition: ",
    "technical prior invalid condition: ",
    "news prior invalid condition: ",
    "marketodds prior invalid condition: ",
  ];
  for (const prefix of prefixesToStrip) {
    if (text.toLowerCase().startsWith(prefix.toLowerCase())) {
      return translateText(text.slice(prefix.length));
    }
  }

  const coordPattern = /Coordinator research view is (neutral|bullish|bearish) \(confidence ([\d.]+), status (\w+)\)/i;
  const coordMatch = text.match(coordPattern);
  if (coordMatch) {
    const dirMap: Record<string, string> = { neutral: "中性", bullish: "偏多", bearish: "偏空" };
    const direction = dirMap[coordMatch[1].toLowerCase()] || coordMatch[1];
    const confidence = Math.round(parseFloat(coordMatch[2]) * 100);
    const statusMap: Record<string, string> = { partial: "部分", complete: "完整", unavailable: "不可用" };
    const status = statusMap[coordMatch[3].toLowerCase()] || coordMatch[3];
    return `综合分析：${direction}（确信度 ${confidence}，数据状态 ${status}）`;
  }

  const phraseMap: [RegExp, string | ((match: string, ...groups: string[]) => string)][] = [
    [/CME options input is unavailable/i, "CME期权数据未接入"],
    [/options (input|data|status) is ['"]?(unavailable|missing)['"]?/i, "期权数据缺失"],
    [/macro (input|data|status) is ['"]?(unavailable|missing)['"]?/i, "宏观数据缺失"],
    [/technical (input|data|status) is ['"]?(unavailable|missing)['"]?/i, "技术面数据缺失"],
    [/news (input|data|status) is ['"]?(unavailable|missing)['"]?/i, "新闻数据缺失"],
    [/market odds (input|data|status) is ['"]?(unavailable|missing)['"]?/i, "市场赔率数据缺失"],
    [/positioning (input|data|status) is ['"]?(unavailable|missing)['"]?/i, "持仓数据缺失"],
    [/10Y real-yield signal is missing/i, "10年期实际利率信号缺失"],
    [/real-yield field/i, "实际利率字段"],
    [/nominal yield/i, "名义收益率"],
    [/T10YIE/i, "T10YIE(盈亏平衡通胀率)"],
    [/prior (agent )?status is (\w+)/gi, (_, _agent: string, status: string) => {
      const map: Record<string, string> = { partial: "部分可用", complete: "完整", unavailable: "不可用", provisional: "临时" };
      return `前置分析状态：${map[status.toLowerCase()] || status}`;
    }],
    [/coordinator view is provisional/i, "协调器视图为临时结论"],
    [/Liquidity indicators are incomplete:\s*/i, "流动性指标不完整："],
    [/Unavailable (macro )?symbols?:?\s*/i, "缺失指标："],
    [/ON RRP/i, "ON RRP(隔夜逆回购)"],
    [/EFFR/i, "EFFR(有效联邦基金利率)"],
    [/RRPONTSYAWARD/i, "RRPONTSYAWARD"],
    [/RRPONTSYD/i, "RRPONTSYD"],
    [/WRESBAL/i, "WRESBAL(准备金余额)"],
    [/View is partial due to missing or conflicting inputs/i, "因数据缺失或冲突，综合判断仅为部分视图"],
    [/Wall scores are missing,? so support\/resistance conviction is limited/i, "期权墙评分缺失，支撑/阻力判断受限"],
    [/checked real-yield fields,? nominal yield and T10YIE\.?/i, "已检查实际利率、名义收益率和盈亏平衡通胀率"],
    [/checked\s+实际利率字段s?,?\s*名义收益率\s*and\s*T10YIE/i, "已检查实际利率、名义收益率和盈亏平衡通胀率"],
    [/composite:\s*stale vs latest eligible context\s*([0-9-]+)/i, (_, date: string) => `综合结论尚未更新到最新可用上下文（${date}）`],
    [/macro:\s*(\d+)\s*available/i, (_, count: string) => `宏观侧已有 ${count} 项可用信号`],
    [/score\s*(\d+(?:\.\d+)?)/i, (_, score: string) => `评分 ${score}`],
    [/(Macro|Options|Risk|Technical|News|MarketOdds) prior agent status is (partial|provisional|complete|unavailable);? coordinator view is provisional\.?/gi,
      (_, module: string, status: string) => {
        const moduleMap: Record<string, string> = {
          Macro: "宏观",
          Options: "期权",
          Risk: "风险层",
          Technical: "技术面",
          News: "新闻",
          MarketOdds: "市场赔率",
        };
        const statusMap: Record<string, string> = {
          partial: "部分可用",
          complete: "完整",
          unavailable: "不可用",
          provisional: "临时",
        };
        return `前置${moduleMap[module] || module}分析${statusMap[status.toLowerCase()] || status}，协调器已给出临时结论`;
      }],
    [/coordinator view is provisional/i, "协调器视图为临时结论"],
    [/Macro prior risk:\s*/i, "宏观风险："],
    [/Options prior risk:\s*/i, "期权风险："],
    [/Risk prior risk:\s*/i, "风险层风险："],
    [/Technical prior risk:\s*/i, "技术面风险："],
    [/News prior risk:\s*/i, "新闻风险："],
    [/MarketOdds prior risk:\s*/i, "市场赔率风险："],
    [/data (is )?unavailable/i, "数据不可用"],
    [/(\w+) status is ['"]?unavailable['"]?/i, "$1状态：不可用"],
    [/\bconfidence\b/gi, "确信度"],
    [/\bsupport\b/gi, "支撑"],
    [/\bresistance\b/gi, "阻力"],
    [/\bvolatility\b/gi, "波动率"],
    [/\bliquidity\b/gi, "流动性"],
    [/\btrend\b/gi, "趋势"],
    [/\breversal\b/gi, "反转"],
    [/\bbreakout\b/gi, "突破"],
    [/\bconsolidation\b/gi, "盘整"],
    [/\bstagflation\b/gi, "滞胀"],
    [/\breflation\b/gi, "再通胀"],
    [/\bdisinflation\b/gi, "去通胀"],
    [/\bhawkish\b/gi, "鹰派"],
    [/\bdovish\b/gi, "鸽派"],
    [/\breal yield\b/gi, "实际利率"],
    [/\bnominal\b/gi, "名义"],
    [/\byield curve\b/gi, "收益率曲线"],
    [/\bmacro\b/gi, "宏观"],
    [/\boptions?\b(?![^a-z])/gi, "期权"],
    [/\bCME\b/, "CME"],
  ];

  let result = text;
  for (const [pattern, replacement] of phraseMap) {
    if (typeof replacement === "function") {
      result = result.replace(pattern, replacement as never);
    } else if (pattern.test(result)) {
      result = result.replace(pattern, replacement);
    }
  }

  const finalMap: [RegExp, string][] = [
    [/\bpartial\b/gi, "部分可用"],
    [/\bprovisional\b/gi, "临时"],
    [/\bunavailable\b/gi, "不可用"],
    [/\bcomplete\b/gi, "完整"],
    [/\bmissing\b/gi, "缺失"],
    [/\bconfirmed_data\b/gi, "确认数据"],
    [/\bexternal_opinion\b/gi, "外部观点"],
    [/\bsystem_inference\b/gi, "系统推断"],
  ];
  for (const [pattern, replacement] of finalMap) {
    result = result.replace(pattern, replacement);
  }

  result = result.replace(/\s{2,}/g, " ").trim();
  result = result.replace(/\.$/g, "");
  result = result.replace(/;\s*$/g, "");
  result = result.replace(/\bneutral\b/gi, "中性");
  result = result.replace(/\bbullish\b/gi, "偏多");
  result = result.replace(/\bbearish\b/gi, "偏空");

  return result || text;
}

export function reviewStatusLabel(status: string | null | undefined): string {
  const value = (status || "").toLowerCase();
  if (value === "success" || value === "supported") return "事实已核验";
  if (value === "needs_review" || value === "conflicted") return "待人工复核";
  if (value === "partial" || value === "partially_supported") return "部分待补证";
  if (value === "unavailable" || value === "unsupported" || value === "contradicted") return "审查有风险";
  if (value === "not_reviewed") return "未审查";
  return "审查状态未知";
}

export function reviewStatusTone(status: string | null | undefined): { color: string; background: string; border: string } {
  const value = (status || "").toLowerCase();
  if (value === "success" || value === "supported") {
    return { color: "#10b981", background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.22)" };
  }
  if (value === "needs_review" || value === "conflicted" || value === "partial" || value === "partially_supported") {
    return { color: "#f59e0b", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.22)" };
  }
  if (value === "unavailable" || value === "unsupported" || value === "contradicted") {
    return { color: "#ef4444", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.22)" };
  }
  return { color: "var(--fg-4)", background: "var(--bg-card-inner)", border: "1px solid var(--border)" };
}
