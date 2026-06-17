import type {
  CMEOptionsLevelItem,
  CMEOptionsSupportResistance,
  CMEOptionsWallScore,
} from "@/types/cme-options";
import { FACard } from "../shared/FACard";
import { FAMetricCard } from "../shared/FAMetricCard";
import { FAStatusPill } from "../shared/FAStatusPill";

interface KeyLevelMapProps {
  supportResistance: CMEOptionsSupportResistance;
  wallScores: CMEOptionsWallScore[];
}

function formatPrice(value: number) {
  return value.toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatScore(value: number) {
  return value.toFixed(2);
}

function formatPercent(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function sortLevels(levels: CMEOptionsLevelItem[]) {
  return [...levels].sort((left, right) => {
    if (right.wall_score !== left.wall_score) return right.wall_score - left.wall_score;
    return right.strike - left.strike;
  });
}

function pickTop(levels: CMEOptionsLevelItem[], limit = 3) {
  return sortLevels(levels).slice(0, limit);
}

function highestResistance(levels: CMEOptionsLevelItem[]) {
  return sortLevels(levels)[0] ?? null;
}

function highestOiStrike(wallScores: CMEOptionsWallScore[]) {
  return [...wallScores].sort((left, right) => {
    if (right.oi !== left.oi) return right.oi - left.oi;
    if (right.wall_score !== left.wall_score) return right.wall_score - left.wall_score;
    return right.strike - left.strike;
  })[0] ?? null;
}

function LevelList({
  title,
  subtitle,
  levels,
  tone,
}: {
  title: string;
  subtitle: string;
  levels: CMEOptionsLevelItem[];
  tone: "call" | "put";
}) {
  const borderClass = tone === "call" ? "border-[var(--down-border)]" : "border-[var(--up-border)]";
  const accentClass = tone === "call" ? "text-[var(--down)]" : "text-[var(--up)]";

  return (
    <FACard
      title={title}
      eyebrow={tone === "call" ? "Call阻力" : "Put支撑"}
      accent={tone === "call" ? "down" : "up"}
      action={<FAStatusPill tone={tone === "call" ? "down" : "up"}>{`${levels.length} 条`}</FAStatusPill>}
      className={`border ${borderClass}`}
      bodyClassName="space-y-2"
    >
      <p className="text-[11px] text-[var(--fg-4)]">{subtitle}</p>
      {levels.map((level, index) => (
        <div
          key={`${tone}-${level.strike}-${index}`}
          className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2.5"
        >
          <div className="min-w-0">
            <div className="fa-num text-[15px] font-semibold text-[var(--fg-2)]">
              {formatPrice(level.strike)}
            </div>
            <div className="mt-0.5 text-[11px] text-[var(--fg-4)]">
              {tone === "call" ? "压制强度" : "支撑强度"} {formatScore(level.wall_score)}
            </div>
          </div>
          <div className={`shrink-0 text-right text-xs font-medium ${accentClass}`}>
            <div>{formatPercent(level.distance_pct)}</div>
            <div className="mt-0.5 text-[10px] text-[var(--fg-5)]">距离</div>
          </div>
        </div>
      ))}
    </FACard>
  );
}

export function KeyLevelMap({ supportResistance, wallScores }: KeyLevelMapProps) {
  const callLevels = pickTop(supportResistance.resistance);
  const putLevels = pickTop(supportResistance.support);
  const pinLevel = highestOiStrike(wallScores);
  const breakthroughBase = highestResistance(supportResistance.resistance);
  const breakthroughStrike = breakthroughBase ? breakthroughBase.strike * 1.03 : null;

  return (
    <FACard title="价位轨道" eyebrow="Level Rail" accent="brand" bodyClassName="space-y-4">
      <p className="text-[11px] text-[var(--fg-4)]">基于当前支撑 / 阻力与墙位数据做轻量解释性展示。</p>
      <div className="grid gap-3 lg:grid-cols-3">
        <LevelList
          title="上方 Call 压制区"
          subtitle="Top 3 阻力位"
          levels={callLevels}
          tone="call"
        />

        <FACard
          title="Pin 位"
          eyebrow="Reference Level"
          accent="info"
          action={<FAStatusPill tone="info">参考位</FAStatusPill>}
          bodyClassName="space-y-3"
        >
          <p className="text-[11px] text-[var(--fg-4)]">由当前墙位中最高持仓 strike 推导。</p>
          <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-3">
            {pinLevel ? (
              <>
                <div className="fa-num text-2xl font-semibold tracking-tight text-[var(--fg-2)]">
                  {formatPrice(pinLevel.strike)}
                </div>
                <div className="mt-1 text-xs text-[var(--fg-4)]">最高 OI: {formatPrice(pinLevel.oi)}</div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-[var(--fg-4)]">
                  <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-panel)] px-2.5 py-2">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">wall_type</div>
                    <div className="mt-0.5 font-medium text-[var(--fg-3)]">{pinLevel.wall_type}</div>
                  </div>
                  <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-panel)] px-2.5 py-2">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">wall_score</div>
                    <div className="mt-0.5 font-medium text-[var(--fg-3)]">
                      {formatScore(pinLevel.wall_score)}
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="text-sm text-[var(--fg-4)]">当前没有可用于计算 Pin 位的 wallScores。</div>
            )}
          </div>
        </FACard>

        <LevelList
          title="下方 Put 支撑区"
          subtitle="Top 3 支撑位"
          levels={putLevels}
          tone="put"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <FAMetricCard label="breakthrough_base" value={breakthroughBase ? formatPrice(breakthroughBase.strike) : "—"} hint="基准阻力位" />
        <FAMetricCard label="breakthrough_level" value={breakthroughStrike ? formatPrice(breakthroughStrike) : "—"} hint="最高阻力位上移 3%" />
        <FAMetricCard label="formula" value="highest_resistance × 1.03" hint="解释性推导，不代表确定突破" />
      </div>
    </FACard>
  );
}
