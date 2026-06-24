import { FACard } from "@/components/shared/FACard";
import { FAConvictionBar } from "@/components/shared/FAConvictionBar";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { StrategyHeroViewModel, StrategyViewModel } from "@/types/strategy";
import { directionIcon, directionTone, formatDate, sourceLabel, sourceTone, statusTone, strategySentence, strategyValueLabel } from "./strategyFormat";
import { SourceRefList } from "./StrategySourceRefs";

export function StrategyHeroSection({
  hero,
  asset,
  sampleSize,
  source,
}: {
  hero: StrategyHeroViewModel;
  asset: string;
  sampleSize: number;
  source: StrategyViewModel["source"];
}) {
  const DirIcon = directionIcon(hero.direction);
  const tone = directionTone(hero.direction);

  return (
    <FACard title="策略概览" eyebrow="当前策略" accent="brand" bodyClassName="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <FAStatusPill tone={statusTone(hero.status)}>{strategyValueLabel(hero.status)}</FAStatusPill>
        <FAStatusPill tone={sourceTone(source)}>{sourceLabel(source)}</FAStatusPill>
        <FAStatusPill tone="info">{asset}</FAStatusPill>
        <FAStatusPill tone="neutral">{sampleSize} 样本</FAStatusPill>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">方向</div>
          <div className="mt-1 flex items-center gap-2">
            <DirIcon size={16} className={tone === "up" ? "text-[var(--up)]" : tone === "down" ? "text-[var(--down)]" : "text-[var(--fg-4)]"} />
            <FAStatusPill tone={tone}>{strategyValueLabel(hero.direction)}</FAStatusPill>
          </div>
        </div>

        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">置信度</div>
          <div className="mt-2">
            <FAConvictionBar
              value={hero.confidence !== null ? hero.confidence * 100 : 0}
              label="确信度"
              tone={hero.direction === "bullish" ? "up" : hero.direction === "bearish" ? "down" : "info"}
            />
          </div>
        </div>

        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">市场状态</div>
          <div className="mt-1 text-[13px] font-semibold text-[var(--fg-2)]">{strategyValueLabel(hero.market_regime)}</div>
        </div>

        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">交易日</div>
          <div className="mt-1 text-[13px] font-semibold text-[var(--fg-2)]">{formatDate(hero.trade_date)}</div>
          {hero.run_id ? <div className="mt-1 text-[9px] text-[var(--fg-5)]">可在溯源详情中查看运行记录</div> : null}
        </div>
      </div>

      {hero.bias ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">策略摘要</div>
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--fg-3)]">{strategySentence(hero.bias)}</p>
        </div>
      ) : null}

      <SourceRefList refs={hero.source_refs} />
    </FACard>
  );
}
