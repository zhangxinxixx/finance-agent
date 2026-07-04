import { FACard } from "@/components/shared/FACard";
import type { StrategyScenarioViewModel } from "@/types/strategy";
import { strategySentence } from "./strategyFormat";

const MAX_CONDITION_ITEMS = 5;
const COLLAPSED_ENGLISH_SUMMARY = "后端返回英文策略摘要，已在主视图折叠；请在溯源或原始报告中查看原文。";

export function StrategyScenarioSection({ scenario }: { scenario: StrategyScenarioViewModel }) {
  const alternativeScenarios = normalizeScenarioItems(scenario.alternative_scenarios);
  const triggerConditions = normalizeScenarioItems(scenario.trigger_conditions);
  const invalidationConditions = normalizeScenarioItems(scenario.invalidation_conditions);
  const confirmationConditions = normalizeScenarioItems(scenario.confirmation_conditions);
  const riskPoints = normalizeScenarioItems(scenario.risk_points);

  return (
    <FACard title="情景分析" eyebrow="情景推演" bodyClassName="space-y-3.5">
      <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3.5 shadow-[0_0_0_1px_rgba(59,130,246,0.04)]">
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">主要情景</div>
        <p className="mt-1 text-[12px] leading-6 text-[var(--fg-1)]">{strategySentence(scenario.main_scenario)}</p>
      </div>

      {alternativeScenarios.items.length > 0 ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">备选情景</div>
          <ul className="mt-1 space-y-1">
            {alternativeScenarios.items.map((alt, idx) => (
              <li key={idx} className="text-[11px] leading-relaxed text-[var(--fg-3)]">
                <span className="mr-1 text-[var(--fg-5)]">-</span> {alt}
              </li>
            ))}
          </ul>
          <ScenarioOverflowNotice overflowCount={alternativeScenarios.overflowCount} collapsedCount={alternativeScenarios.collapsedCount} />
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

      <ConditionList label="触发条件" result={triggerConditions} />
      <ConditionList label="失效条件" result={invalidationConditions} />
      <ConditionList label="确认条件" result={confirmationConditions} />
      <ConditionList label="风险点" result={riskPoints} />
    </FACard>
  );
}

interface NormalizedScenarioItems {
  items: string[];
  collapsedCount: number;
  overflowCount: number;
}

function normalizeScenarioItems(items: string[]): NormalizedScenarioItems {
  const seen = new Set<string>();
  const normalized: string[] = [];
  let collapsedCount = 0;

  for (const item of items) {
    const text = strategySentence(item);
    if (!text) continue;
    if (text === COLLAPSED_ENGLISH_SUMMARY) collapsedCount += 1;
    if (seen.has(text)) continue;
    seen.add(text);
    normalized.push(text);
  }

  return {
    items: normalized.slice(0, MAX_CONDITION_ITEMS),
    collapsedCount,
    overflowCount: Math.max(0, normalized.length - MAX_CONDITION_ITEMS),
  };
}

function ScenarioOverflowNotice({ overflowCount, collapsedCount }: { overflowCount: number; collapsedCount: number }) {
  if (!overflowCount && collapsedCount <= 1) return null;

  const parts = [
    overflowCount > 0 ? `另有 ${overflowCount} 条已收起` : null,
    collapsedCount > 1 ? `${collapsedCount} 条英文原文已合并` : null,
  ].filter(Boolean);

  return <div className="mt-2 text-[10px] leading-5 text-[var(--fg-5)]">{parts.join("，")}；详见溯源或原始报告。</div>;
}

function ConditionList({ label, result }: { label: string; result: NormalizedScenarioItems }) {
  if (!result.items.length) return null;
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <ul className="mt-1 space-y-0.5">
        {result.items.map((item, idx) => (
          <li key={idx} className="text-[11px] leading-relaxed text-[var(--fg-3)]">
            <span className="mr-1 text-[var(--fg-5)]">&#8226;</span> {item}
          </li>
        ))}
      </ul>
      <ScenarioOverflowNotice overflowCount={result.overflowCount} collapsedCount={result.collapsedCount} />
    </div>
  );
}
