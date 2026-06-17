import { Crosshair } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { StrategyModuleSignal, StrategyPlaybookMatch } from "@/types/strategy";
import { moduleIcon, moduleStatusTone, strategySentence, strategyValueLabel } from "./strategyFormat";
import { SourceRefList } from "./StrategySourceRefs";

export function StrategyModuleSignalsSection({ signals }: { signals: StrategyModuleSignal[] }) {
  if (!signals.length) return null;
  return (
    <FACard title="模块信号" eyebrow="Modules" bodyClassName="space-y-2">
      {signals.map((signal) => {
        const Icon = moduleIcon(signal.module);
        const tone = moduleStatusTone(signal.status);
        return (
          <div
            key={signal.module}
            className="flex items-start gap-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3"
          >
            <Icon size={16} className="mt-0.5 shrink-0 text-[var(--fg-4)]" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-[12px] font-semibold text-[var(--fg-2)]">{signal.label}</span>
                <FAStatusPill tone={tone} dot={false}>{strategyValueLabel(signal.status)}</FAStatusPill>
              </div>
              {signal.summary ? (
                <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--fg-4)]">{strategySentence(signal.summary)}</p>
              ) : null}
              <SourceRefList refs={signal.source_refs} />
            </div>
          </div>
        );
      })}
    </FACard>
  );
}

export function StrategyPlaybookMatchesSection({ matches }: { matches: StrategyPlaybookMatch[] }) {
  if (!matches.length) return null;
  return (
    <FACard title="剧本模板匹配" eyebrow="执行剧本" bodyClassName="space-y-2">
      {matches.map((match) => (
        <div
          key={match.playbook_id}
          className="flex items-start gap-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3"
        >
          <Crosshair size={14} className="mt-0.5 shrink-0 text-[var(--fg-4)]" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-[12px] font-semibold text-[var(--fg-2)]">{match.title}</span>
              <span className="fa-num rounded-[var(--radius-sm)] border border-[var(--info-border)] bg-[var(--info-soft)] px-1.5 py-0.5 text-[9px] font-semibold text-[var(--info)]">
                {Math.round(match.match_score * 100)}%
              </span>
            </div>
            {match.rule_id ? (
              <div className="mt-0.5 text-[9px] text-[var(--fg-5)]">规则编号：{match.rule_id}</div>
            ) : null}
            <SourceRefList refs={match.source_refs} />
          </div>
        </div>
      ))}
    </FACard>
  );
}
