import { FACard } from "@/components/shared/FACard";
import type { StrategyScenarioViewModel } from "@/types/strategy";
import { strategySentence } from "./strategyFormat";

export function StrategyScenarioSection({ scenario }: { scenario: StrategyScenarioViewModel }) {
  return (
    <FACard title="情景分析" eyebrow="情景推演" bodyClassName="space-y-3.5">
      <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3.5 shadow-[0_0_0_1px_rgba(59,130,246,0.04)]">
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">主要情景</div>
        <p className="mt-1 text-[12px] leading-6 text-[var(--fg-1)]">{strategySentence(scenario.main_scenario)}</p>
      </div>

      {scenario.alternative_scenarios.length > 0 ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">备选情景</div>
          <ul className="mt-1 space-y-1">
            {scenario.alternative_scenarios.map((alt, idx) => (
              <li key={idx} className="text-[11px] leading-relaxed text-[var(--fg-3)]">
                <span className="mr-1 text-[var(--fg-5)]">-</span> {strategySentence(alt)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">阻力位</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {scenario.key_levels.resistance.length > 0 ? (
              scenario.key_levels.resistance.map((level, idx) => (
                <span key={idx} className="fa-num rounded-[var(--radius-sm)] border border-[var(--down-border)] bg-[var(--down-soft)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--down)]">
                  {level}
                </span>
              ))
            ) : (
              <span className="text-[10px] text-[var(--fg-5)]">--</span>
            )}
          </div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">支撑位</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {scenario.key_levels.support.length > 0 ? (
              scenario.key_levels.support.map((level, idx) => (
                <span key={idx} className="fa-num rounded-[var(--radius-sm)] border border-[var(--up-border)] bg-[var(--up-soft)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--up)]">
                  {level}
                </span>
              ))
            ) : (
              <span className="text-[10px] text-[var(--fg-5)]">--</span>
            )}
          </div>
        </div>
      </div>

      <ConditionList label="触发条件" items={scenario.trigger_conditions} />
      <ConditionList label="失效条件" items={scenario.invalidation_conditions} />
      <ConditionList label="确认条件" items={scenario.confirmation_conditions} />
      <ConditionList label="风险点" items={scenario.risk_points} />
    </FACard>
  );
}

function ConditionList({ label, items }: { label: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <ul className="mt-1 space-y-0.5">
        {items.map((item, idx) => (
          <li key={idx} className="text-[11px] leading-relaxed text-[var(--fg-3)]">
            <span className="mr-1 text-[var(--fg-5)]">&#8226;</span> {strategySentence(item)}
          </li>
        ))}
      </ul>
    </div>
  );
}
