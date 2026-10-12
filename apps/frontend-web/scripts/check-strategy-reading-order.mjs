import assert from "node:assert/strict";

const {
  cmePathStatusLabel,
  dataStatusLabel,
  enumRawTitle,
  liveMarketStatusLabel,
  liveStrategyScenarioStatusLabel,
  preserveStrategyItems,
  shadowClassificationLabel,
  shadowLifecycleLabel,
  shadowOutcomeStatusLabel,
  strategyEvidenceLabel,
  strategyAssetLabel,
  strategySourceLabel,
  strategyTimestampLabel,
  strategyValueLabel,
} = await import("../src/components/strategy/strategyDisplayLabels.ts");

const conditions = [
  "接近主支撑",
  "5m 收盘确认",
  "15m 回踩不失守",
  "波动率缓冲满足",
  "风险收益比达到后端阈值",
  "事件风险窗口结束",
  "数据源时间戳仍在允许窗口",
];
const copiedConditions = preserveStrategyItems(conditions);
assert.deepEqual(copiedConditions, conditions, "decision conditions must keep every backend item");
assert.notEqual(copiedConditions, conditions, "condition rendering must receive a defensive copy");
copiedConditions.pop();
assert.equal(conditions.length, 7, "display preparation must not mutate backend condition arrays");
assert.deepEqual(preserveStrategyItems(null), [], "missing condition arrays must become an explicit empty list");

assert.equal(liveStrategyScenarioStatusLabel("triggered").label, "已触发");
assert.equal(liveStrategyScenarioStatusLabel("blocked_rr").label, "收益风险阻断");
const unknownScenario = liveStrategyScenarioStatusLabel("backend_future_status");
assert.equal(unknownScenario.known, false);
assert.equal(unknownScenario.label, "未知场景状态（技术值见依据记录）");
assert.equal(enumRawTitle(unknownScenario), "未知场景状态（技术值见依据记录）");

assert.equal(liveMarketStatusLabel("available").label, "行情可用");
assert.equal(liveMarketStatusLabel("stale").label, "行情已过期");
const unknownMarket = liveMarketStatusLabel("feed_delayed_v2");
assert.equal(unknownMarket.label, "未知行情状态（技术值见依据记录）");
assert.equal(strategyValueLabel("bullish").label, "看多");
assert.equal(strategyValueLabel("new_regime").label, "未知业务值（技术值见依据记录）");
assert.equal(strategyAssetLabel("SILVERUSD"), "未解释资产（技术记录可核对）");
assert.equal(strategyEvidenceLabel("bullish"), "看多");
const rawCondition = "price accepts above the Gamma Flip band and confirms on retest";
assert.equal(
  strategyEvidenceLabel(rawCondition),
  "中文说明缺口：后端英文说明尚未整理（原文见依据记录）",
  "untranslated backend conditions must declare the Chinese explanation gap without exposing raw text",
);
assert.equal(strategyEvidenceLabel("backend_future_condition"), "中文说明缺口：技术路径或机器字段尚未转换（技术值见依据记录）");
assert.equal(strategyEvidenceLabel("/api/live-strategy/latest"), "中文说明缺口：技术路径或机器字段尚未转换（技术值见依据记录）");
assert.equal(strategyEvidenceLabel("XAUUSD 宏观分析报告"), "XAUUSD 宏观分析报告");
assert.equal(strategyEvidenceLabel("4162.8"), "4162.8", "provided numeric evidence is not a missing explanation");
assert.doesNotMatch(strategyEvidenceLabel("XAUUSD 依据 source_refs /api/unknown"), /source_refs|\/api\//, "a known asset symbol cannot bypass unknown technical-field filtering");
assert.equal(strategyEvidenceLabel("blocked_data"), "数据完整性条件未通过");
assert.equal(strategyEvidenceLabel("Gold macro readiness partial: 0/9 mainlines ready."), "黄金宏观就绪度为部分可用：9 条主线中 0 条就绪。");
assert.equal(strategyEvidenceLabel("Macro prior invalid condition: DXY daily/weekly/monthly delta is missing; dollar direction must remain unconfirmed."), "宏观先验失效条件：缺少 DXY 日/周/月变动；美元方向必须保持未核验。");
assert.equal(strategyEvidenceLabel("期权 前置风险：Data quality reports 4000 PRELIM-derived option rows/signals."), "期权 前置风险：数据质量显示有 4000 行/信号来自初步发布数据。");
assert.equal(strategySourceLabel("bls_public_api_v2"), "美国劳工统计局公开接口");
assert.equal(strategyTimestampLabel("canonical_closed_at"), "规范化 K 线收盘时间");
assert.equal(strategyTimestampLabel("unknown_timestamp"), "数据时间字段未解释（技术记录可核对）");

assert.equal(cmePathStatusLabel("confirmed").label, "已确认");
assert.equal(dataStatusLabel("PRELIM").label, "初步发布");
assert.equal(shadowLifecycleLabel("triggered_then_invalidated").label, "触发后失效");
assert.equal(shadowLifecycleLabel("never_triggered").label, "未触发");
assert.equal(shadowOutcomeStatusLabel("blocked").label, "质量阻断");
assert.equal(shadowClassificationLabel("incorrect").label, "判断错误");
assert.equal(shadowClassificationLabel("hold").label, "观望（HOLD）");
assert.equal(shadowClassificationLabel("new_classification").known, false);

console.log("Strategy reading-order and enum presentation behavior OK");
