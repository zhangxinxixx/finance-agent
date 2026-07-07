import {
  formatGoldMainlineLabel,
  formatGoldNetBiasLabel,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMainlineRanking } from "@/types/gold-mainlines";
import { formatGoldScore, rankingMainlineId, scoreFormulaLabel } from "./goldOverviewFormat";

interface TopMainlinesStripProps {
  rankings: GoldMainlineRanking[];
  limit?: number;
}

export function TopMainlinesStrip({ rankings, limit = 5 }: TopMainlinesStripProps) {
  const topRankings = [...rankings]
    .sort((left, right) => left.rank - right.rank)
    .slice(0, limit);

  if (!topRankings.length) return null;

  return (
    <div className="space-y-1.5">
      {topRankings.map((item) => {
        const mainlineId = rankingMainlineId(item);
        return (
          <div
            key={`${mainlineId ?? item.label ?? "mainline"}-${item.rank}`}
            className="grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5"
          >
            <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-5)]">#{item.rank}</span>
            <div className="min-w-0">
              <div className="truncate text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">
                {item.label || formatGoldMainlineLabel(mainlineId)}
              </div>
              <div className="truncate text-[length:var(--type-caption)] text-[var(--fg-5)]">{formatGoldNetBiasLabel(item.direction)}</div>
            </div>
            <div className="text-right">
              <div className="fa-num text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">{formatGoldScore(item.theme_score ?? item.score)}</div>
              <div className="fa-num text-[length:var(--type-caption)] text-[var(--fg-5)]">D/I/C/F {scoreFormulaLabel(item)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
