import { Ban, CheckCircle2, CircleAlert, ShieldAlert, Target } from "lucide-react";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import type { LiveStrategyNoTrade, LiveStrategySetup } from "@/types/live-strategy";
import { liveStrategyScenarioStatusLabel, preserveStrategyItems, strategyEvidenceLabel } from "./strategyDisplayLabels";

interface LiveStrategyScenariosProps {
  activeScenario: "long" | "short" | "no_trade" | null;
  setups: LiveStrategySetup[];
  noTrade: LiveStrategyNoTrade;
  dataBlocked: boolean;
  strategyStatus: "WAITING" | "WATCHING" | "ARMED" | "TRIGGERED" | "SUSPENDED_DATA";
}

function formatNumber(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatRange(range: [number, number] | null) {
  return range ? `${formatNumber(range[0])} – ${formatNumber(range[1])}` : "—";
}

function levelRoleLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    primary_resistance: "主压力",
    secondary_resistance: "次级压力",
    primary_support: "主支撑",
    secondary_support: "次级支撑",
    gamma_flip: "伽马转换带",
    magnet_pin: "磁吸位",
    tail_protection: "尾部保护",
  };
  if (!value) return "未提供关键位角色";
  return labels[value] ?? `未解释关键位角色（${value}）`;
}

function scenarioTone(status: LiveStrategySetup["status"]): FAStatusTone {
  if (status === "triggered") return "up";
  if (status === "armed" || status === "blocked_rr") return "warn";
  if (status === "watching") return "info";
  return "dim";
}

function ListValue({ items, empty }: { items: string[]; empty: string }) {
  return items.length > 0 ? <ul>{items.map((item, index) => <li key={`${item}-${index}`}>{strategyEvidenceLabel(item)}</li>)}</ul> : <p>{empty}</p>;
}

function SetupCard({ setup, activeScenario, dataBlocked }: { setup: LiveStrategySetup; activeScenario: LiveStrategyScenariosProps["activeScenario"]; dataBlocked: boolean }) {
  const isBlocked = dataBlocked || setup.status === "blocked_data";
  const status = isBlocked ? "blocked_data" : setup.status;
  const hasCoreValues = Boolean(setup.reference_level || setup.entry_zone || setup.invalidation_level !== null || setup.stop_reference !== null);
  const targets = ["TP1", "TP2", "TP3"].map((label) => ({
    label,
    target: setup.targets.find((item) => item.label?.toUpperCase() === label) ?? null,
    riskReward: setup.risk_reward[label.toLowerCase() as keyof LiveStrategySetup["risk_reward"]],
  }));
  const targetLabel = (value: string) => value === "TP1" ? "目标1（TP1）" : value === "TP2" ? "目标2（TP2）" : "目标3（TP3）";
  const hasTargets = targets.some(({ target, riskReward }) => target?.price !== null && target?.price !== undefined || riskReward !== null);
  const statusMeta = liveStrategyScenarioStatusLabel(status);
  const triggerConditions = preserveStrategyItems(setup.trigger_conditions);
  const confirmationConditions = preserveStrategyItems(setup.confirmation_conditions);
  const gateReasons = preserveStrategyItems(setup.gate.reasons);

  return (
    <article className="live-strategy-scenario-card">
      <div className="live-strategy-panel-heading">
        <div><Target size={15} aria-hidden="true" /><h2>{setup.direction === "long" ? "多头场景" : "空头场景"}</h2></div>
        <FAStatusPill tone={scenarioTone(status)}>{statusMeta.label}</FAStatusPill>
      </div>
      {activeScenario === setup.direction ? <p className="live-strategy-scenario-active"><CheckCircle2 size={14} aria-hidden="true" />后端标记为当前场景</p> : null}
      {isBlocked ? <p className="live-strategy-scenario-blocked"><CircleAlert size={14} aria-hidden="true" />数据阻断：后端未确认完整行情数据，以下仅保留只读字段。</p> : null}
      {hasCoreValues ? (
        <div className="live-strategy-scenario-values">
          <div><span>参考位</span><strong>{levelRoleLabel(setup.reference_level?.role)} <b className="fa-num">{formatNumber(setup.reference_level?.value)}</b></strong></div>
          <div><span>入场区</span><strong className="fa-num">{formatRange(setup.entry_zone)}</strong></div>
          <div><span>失效位</span><strong className="fa-num">{formatNumber(setup.invalidation_level)}</strong></div>
          <div><span>止损参考</span><strong className="fa-num">{formatNumber(setup.stop_reference)}</strong></div>
        </div>
      ) : null}
      {hasTargets ? (
        <div className="live-strategy-scenario-targets" aria-label={`${setup.direction === "long" ? "多头" : "空头"}目标与风险收益比`}>
          {targets.map(({ label, target, riskReward }) => (
            <div key={label}>
              <span>{targetLabel(label)}</span>
              <strong className="fa-num">{formatNumber(target?.price)}</strong>
              <small>{target?.source_role ?? "后端未提供来源角色"}</small>
              <b className="fa-num">风险收益比（RR） {formatNumber(riskReward)}</b>
            </div>
          ))}
        </div>
      ) : null}
      <div className="live-strategy-scenario-lists">
        <div><span>触发条件</span><ListValue items={triggerConditions} empty="后端未提供触发条件。" /></div>
        <div><span>确认条件</span><ListValue items={confirmationConditions} empty="后端未提供确认条件。" /></div>
        <div><span>条件门禁阻断</span><ListValue items={gateReasons} empty={setup.gate.passed ? "后端条件门禁已通过。" : "后端未提供条件门禁原因。"} /></div>
      </div>
    </article>
  );
}

function NoTradeCard({ noTrade, activeScenario, dataBlocked }: { noTrade: LiveStrategyNoTrade; activeScenario: LiveStrategyScenariosProps["activeScenario"]; dataBlocked: boolean }) {
  return (
    <article className="live-strategy-scenario-card live-strategy-no-trade-card">
      <div className="live-strategy-panel-heading">
        <div><Ban size={15} aria-hidden="true" /><h2>不交易场景</h2></div>
        <FAStatusPill tone={dataBlocked ? "dim" : "neutral"}>{dataBlocked ? "数据阻断" : "不交易"}</FAStatusPill>
      </div>
      {activeScenario === "no_trade" ? <p className="live-strategy-scenario-active"><CheckCircle2 size={14} aria-hidden="true" />后端标记为当前场景</p> : null}
      {dataBlocked ? <p className="live-strategy-scenario-blocked"><CircleAlert size={14} aria-hidden="true" />数据阻断：等待后端恢复完整数据。</p> : null}
      <div className="live-strategy-no-trade-range"><span>观望区间</span><strong className="fa-num">{formatRange(noTrade.range)}</strong></div>
      <div className="live-strategy-scenario-lists">
        <div><span>不交易原因</span><ListValue items={preserveStrategyItems(noTrade.reasons)} empty="后端未提供不交易原因。" /></div>
        <div><span>等待条件</span><ListValue items={preserveStrategyItems(noTrade.waiting_conditions)} empty="后端未提供等待条件。" /></div>
      </div>
    </article>
  );
}

export function LiveStrategyScenarios({ activeScenario, setups, noTrade, dataBlocked, strategyStatus }: LiveStrategyScenariosProps) {
  const longSetup = setups.find((setup) => setup.direction === "long");
  const shortSetup = setups.find((setup) => setup.direction === "short");
  const fallbackSetup = (direction: "long" | "short"): LiveStrategySetup => ({ direction, status: "unavailable", setup_id: null, reference_level: null, entry_zone: null, trigger_conditions: [], confirmation_conditions: [], invalidation_level: null, stop_reference: null, volatility_buffer: null, spread_buffer: null, targets: [], risk_reward: { tp1: null, tp2: null, tp3: null }, gate: { passed: false, reasons: [] }, calculation: { ruleset: null, inputs: {} } });
  const orderedSetups = [longSetup ?? fallbackSetup("long"), shortSetup ?? fallbackSetup("short")]
    .sort((left, right) => Number(right.direction === activeScenario && !dataBlocked) - Number(left.direction === activeScenario && !dataBlocked));
  const visibleActiveScenario = dataBlocked ? null : activeScenario;

  return (
    <section className="live-strategy-scenarios" aria-label="后端实时策略场景">
      <div className="live-strategy-scenarios-heading">
        <div><ShieldAlert size={15} aria-hidden="true" /><h2>场景剧本</h2></div>
        <span>当前场景：<b>{dataBlocked ? "无法核验（上次结果仅供复盘）" : visibleActiveScenario ?? (strategyStatus === "WAITING" ? "等待关键位接近/确认" : strategyStatus === "SUSPENDED_DATA" ? "后端数据暂停" : "尚未激活")}</b></span>
      </div>
      <div className="live-strategy-scenarios-grid">
        {visibleActiveScenario === "no_trade" ? <NoTradeCard noTrade={noTrade} activeScenario={visibleActiveScenario} dataBlocked={dataBlocked} /> : null}
        {orderedSetups.map((setup) => <SetupCard key={setup.direction} setup={setup} activeScenario={visibleActiveScenario} dataBlocked={dataBlocked} />)}
        {visibleActiveScenario !== "no_trade" ? <NoTradeCard noTrade={noTrade} activeScenario={visibleActiveScenario} dataBlocked={dataBlocked} /> : null}
      </div>
    </section>
  );
}
