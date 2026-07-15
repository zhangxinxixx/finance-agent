import { Ban, CheckCircle2, CircleAlert, ShieldAlert, Target } from "lucide-react";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import type { LiveStrategyNoTrade, LiveStrategySetup } from "@/types/live-strategy";

interface LiveStrategyScenariosProps {
  activeScenario: "long" | "short" | "no_trade" | null;
  setups: LiveStrategySetup[];
  noTrade: LiveStrategyNoTrade;
  dataBlocked: boolean;
}

function formatNumber(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatRange(range: [number, number] | null) {
  return range ? `${formatNumber(range[0])} – ${formatNumber(range[1])}` : "—";
}

function scenarioTone(status: LiveStrategySetup["status"]): FAStatusTone {
  if (status === "triggered") return "up";
  if (status === "armed" || status === "blocked_rr") return "warn";
  if (status === "watching") return "info";
  return "dim";
}

function ListValue({ items, empty }: { items: string[]; empty: string }) {
  return items.length > 0 ? <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul> : <p>{empty}</p>;
}

function SetupCard({ setup, activeScenario, dataBlocked }: { setup: LiveStrategySetup; activeScenario: LiveStrategyScenariosProps["activeScenario"]; dataBlocked: boolean }) {
  const isBlocked = dataBlocked || setup.status === "blocked_data";
  const status = isBlocked ? "blocked_data" : setup.status;
  const targets = ["TP1", "TP2", "TP3"].map((label) => ({
    label,
    target: setup.targets.find((item) => item.label?.toUpperCase() === label) ?? null,
    riskReward: setup.risk_reward[label.toLowerCase() as keyof LiveStrategySetup["risk_reward"]],
  }));

  return (
    <article className="live-strategy-scenario-card">
      <div className="live-strategy-panel-heading">
        <div><Target size={15} aria-hidden="true" /><h2>{setup.direction === "long" ? "多头场景" : "空头场景"}</h2></div>
        <FAStatusPill tone={scenarioTone(status)}>{status}</FAStatusPill>
      </div>
      {activeScenario === setup.direction ? <p className="live-strategy-scenario-active"><CheckCircle2 size={14} aria-hidden="true" />后端标记为当前场景</p> : null}
      {isBlocked ? <p className="live-strategy-scenario-blocked"><CircleAlert size={14} aria-hidden="true" />blocked_data：后端未确认完整行情数据，以下仅保留只读字段。</p> : null}
      <div className="live-strategy-scenario-values">
        <div><span>Reference</span><strong>{setup.reference_level?.role ?? "—"} <b className="fa-num">{formatNumber(setup.reference_level?.value)}</b></strong></div>
        <div><span>Entry Zone</span><strong className="fa-num">{formatRange(setup.entry_zone)}</strong></div>
        <div><span>Invalidation</span><strong className="fa-num">{formatNumber(setup.invalidation_level)}</strong></div>
        <div><span>Stop</span><strong className="fa-num">{formatNumber(setup.stop_reference)}</strong></div>
      </div>
      <div className="live-strategy-scenario-targets" aria-label={`${setup.direction} targets and risk reward`}>
        {targets.map(({ label, target, riskReward }) => (
          <div key={label}>
            <span>{label}</span>
            <strong className="fa-num">{formatNumber(target?.price)}</strong>
            <small>{target?.source_role ?? "后端未提供来源角色"}</small>
            <b className="fa-num">RR {formatNumber(riskReward)}</b>
          </div>
        ))}
      </div>
      <div className="live-strategy-scenario-lists">
        <div><span>触发条件</span><ListValue items={setup.trigger_conditions} empty="后端未提供触发条件。" /></div>
        <div><span>确认条件</span><ListValue items={setup.confirmation_conditions} empty="后端未提供确认条件。" /></div>
        <div><span>Gate reasons</span><ListValue items={setup.gate.reasons} empty={setup.gate.passed ? "后端 Gate 已通过。" : "后端未提供 Gate 原因。"} /></div>
      </div>
    </article>
  );
}

function NoTradeCard({ noTrade, activeScenario, dataBlocked }: { noTrade: LiveStrategyNoTrade; activeScenario: LiveStrategyScenariosProps["activeScenario"]; dataBlocked: boolean }) {
  return (
    <article className="live-strategy-scenario-card live-strategy-no-trade-card">
      <div className="live-strategy-panel-heading">
        <div><Ban size={15} aria-hidden="true" /><h2>不交易场景</h2></div>
        <FAStatusPill tone={dataBlocked ? "dim" : "neutral"}>{dataBlocked ? "blocked_data" : "no_trade"}</FAStatusPill>
      </div>
      {activeScenario === "no_trade" ? <p className="live-strategy-scenario-active"><CheckCircle2 size={14} aria-hidden="true" />后端标记为当前场景</p> : null}
      {dataBlocked ? <p className="live-strategy-scenario-blocked"><CircleAlert size={14} aria-hidden="true" />blocked_data：等待后端恢复完整数据。</p> : null}
      <div className="live-strategy-no-trade-range"><span>Range</span><strong className="fa-num">{formatRange(noTrade.range)}</strong></div>
      <div className="live-strategy-scenario-lists">
        <div><span>Reasons</span><ListValue items={noTrade.reasons} empty="后端未提供不交易原因。" /></div>
        <div><span>Waiting conditions</span><ListValue items={noTrade.waiting_conditions} empty="后端未提供等待条件。" /></div>
      </div>
    </article>
  );
}

export function LiveStrategyScenarios({ activeScenario, setups, noTrade, dataBlocked }: LiveStrategyScenariosProps) {
  const longSetup = setups.find((setup) => setup.direction === "long");
  const shortSetup = setups.find((setup) => setup.direction === "short");

  return (
    <section className="live-strategy-scenarios" aria-label="后端实时策略场景">
      <div className="live-strategy-scenarios-heading">
        <div><ShieldAlert size={15} aria-hidden="true" /><h2>确定性风险场景</h2></div>
        <span>Active scenario: <b>{activeScenario ?? "—"}</b></span>
      </div>
      <div className="live-strategy-scenarios-grid">
        {longSetup ? <SetupCard setup={longSetup} activeScenario={activeScenario} dataBlocked={dataBlocked} /> : <SetupCard setup={{ direction: "long", status: "unavailable", setup_id: null, reference_level: null, entry_zone: null, trigger_conditions: [], confirmation_conditions: [], invalidation_level: null, stop_reference: null, volatility_buffer: null, spread_buffer: null, targets: [], risk_reward: { tp1: null, tp2: null, tp3: null }, gate: { passed: false, reasons: [] }, calculation: { ruleset: null, inputs: {} } }} activeScenario={activeScenario} dataBlocked={dataBlocked} />}
        {shortSetup ? <SetupCard setup={shortSetup} activeScenario={activeScenario} dataBlocked={dataBlocked} /> : <SetupCard setup={{ direction: "short", status: "unavailable", setup_id: null, reference_level: null, entry_zone: null, trigger_conditions: [], confirmation_conditions: [], invalidation_level: null, stop_reference: null, volatility_buffer: null, spread_buffer: null, targets: [], risk_reward: { tp1: null, tp2: null, tp3: null }, gate: { passed: false, reasons: [] }, calculation: { ruleset: null, inputs: {} } }} activeScenario={activeScenario} dataBlocked={dataBlocked} />}
        <NoTradeCard noTrade={noTrade} activeScenario={activeScenario} dataBlocked={dataBlocked} />
      </div>
    </section>
  );
}
