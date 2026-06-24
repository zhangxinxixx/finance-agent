import { Target } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type { EventFlowTableRow } from "@/types/event-flow";

interface ImpactAssetsProps {
  table: EventFlowTableRow[];
}

interface AssetImpact {
  name: string;
  count: number;
  dominant: "利多黄金" | "利空黄金" | "混合";
  events: string[];
}

function aggregateAssets(table: EventFlowTableRow[]): AssetImpact[] {
  const map = new Map<string, { count: number; impacts: Record<string, number>; events: string[] }>();

  for (const row of table) {
    const names = row.assets.split(",").map((a) => a.trim()).filter(Boolean);
    for (const name of names) {
      const existing = map.get(name) ?? { count: 0, impacts: {}, events: [] };
      existing.count += 1;
      existing.impacts[row.impact] = (existing.impacts[row.impact] ?? 0) + 1;
      if (existing.events.length < 3) {
        existing.events.push(row.title.slice(0, 24));
      }
      map.set(name, existing);
    }
  }

  return Array.from(map.entries())
    .map(([name, data]) => {
      const dominant: AssetImpact["dominant"] =
        (data.impacts["利空黄金"] ?? 0) > (data.impacts["利多黄金"] ?? 0)
          ? "利空黄金"
          : (data.impacts["利多黄金"] ?? 0) > (data.impacts["利空黄金"] ?? 0)
            ? "利多黄金"
            : "混合";
      return { name, count: data.count, dominant, events: data.events };
    })
    .sort((a, b) => b.count - a.count);
}

const IMPACT_STYLE: Record<string, { color: string; bg: string; border: string }> = {
  "利多黄金": { color: "#34d399", bg: "rgba(52,211,153,0.14)", border: "rgba(52,211,153,0.30)" },
  "利空黄金": { color: "#f05252", bg: "rgba(240,82,82,0.14)", border: "rgba(240,82,82,0.30)" },
  "混合": { color: "#fbbf24", bg: "rgba(251,191,36,0.14)", border: "rgba(251,191,36,0.30)" },
};

export function ImpactAssets({ table }: ImpactAssetsProps) {
  const assets = aggregateAssets(table);

  return (
    <FACard
      title={
        <div className="flex items-center gap-2">
          <Target size={12} className="text-[var(--brand-hover)]" />
          <span>影响资产</span>
        </div>
      }
      eyebrow="资产影响"
      accent="brand"
    >
      {assets.length === 0 ? (
        <FAEmptyState title="暂无资产数据" description="当前事件未关联资产。" className="p-4" />
      ) : (
        <div className="flex flex-col gap-1.5">
          {assets.map((asset) => {
            const style = IMPACT_STYLE[asset.dominant];
            return (
              <div
                key={asset.name}
                className="flex items-center gap-2 rounded-[3px] border px-2.5 py-2 transition-[background] hover:bg-[var(--bg-hover)]"
                style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}
              >
                {/* Asset name */}
                <span className="fa-num w-[56px] shrink-0 text-[11px] font-bold text-[var(--fg-2)]">
                  {asset.name}
                </span>

                {/* Impact badge */}
                <span
                  className="shrink-0 rounded-[2px] border px-1.5 py-px text-[10px] font-semibold"
                  style={{ background: style.bg, borderColor: style.border, color: style.color }}
                >
                  {asset.dominant}
                </span>

                {/* Event count */}
                <span className="ml-auto font-mono text-[10px] text-[var(--fg-5)]">
                  {asset.count} 事件
                </span>
              </div>
            );
          })}
        </div>
      )}
    </FACard>
  );
}
