interface DataFreshnessBarProps {
  dataDate: string | null;
  stalenessDays: number | null;
}

export function DataFreshnessBar({ dataDate, stalenessDays }: DataFreshnessBarProps) {
  if (!dataDate) return null;

  const freshnessColor =
    stalenessDays === null || stalenessDays > 7
      ? "var(--down)"
      : stalenessDays > 2
        ? "var(--warn)"
        : "var(--up)";

  const freshnessLabel =
    stalenessDays === null
      ? "无数据"
      : stalenessDays === 0
        ? "今天"
        : stalenessDays === 1
          ? "1天前"
          : `${stalenessDays}天前`;

  return (
    <div
      className="flex items-center gap-2 rounded-[var(--radius-md)] px-3 py-1.5 shrink-0"
      style={{
        background: `${freshnessColor}10`,
        border: `1px solid ${freshnessColor}25`,
      }}
    >
      <div
        className="rounded-full shrink-0"
        style={{ width: 6, height: 6, background: freshnessColor, boxShadow: `0 0 8px ${freshnessColor}` }}
      />
      <span className="text-[10px] font-semibold text-[var(--fg-3)]">
        最新数据日期:
      </span>
      <span className="fa-num text-[11px] font-bold" style={{ color: freshnessColor }}>
        {dataDate}
      </span>
      <span className="text-[9px] font-semibold px-1.5 py-px rounded-full" style={{ background: `${freshnessColor}18`, color: freshnessColor }}>
        {freshnessLabel}
      </span>
    </div>
  );
}
