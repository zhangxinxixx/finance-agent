import { Activity } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type { EventFlowSentimentItem } from "@/types/event-flow";

function SentimentCard({ item }: { item: EventFlowSentimentItem }) {
  const deltaColor = item.deltaDir === "up" ? "#10b981" : "#f05252";
  const values = item.points;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const W = 80;
  const H = 26;
  const toY = (v: number) => H - 3 - ((v - min) / (max - min + 0.1)) * (H - 6);
  const uid = item.label.replace(/\s/g, "");

  const linePoints = values.map((v, i) => `${(i / (values.length - 1)) * W},${toY(v)}`).join(" ");
  const areaPoints = `${linePoints} ${W},${H} 0,${H}`;
  const barWidth = W / values.length - 1;

  return (
    <div
      className="flex min-w-0 flex-1 flex-col rounded-[4px] border px-[12px] py-[10px]"
      style={{
        background: "var(--bg-card-inner)",
        borderColor: "var(--border-faint)",
        borderTop: `2px solid ${item.accent}`,
      }}
    >
      <div className="mb-1 text-[10px] font-medium leading-[1.3] text-[var(--fg-5)]">{item.label}</div>
      <div className="mb-[3px] flex items-baseline gap-[2px]">
        <span className="fa-num text-[22px] font-bold leading-none text-[var(--fg-1)]">{item.value}</span>
        <span className="text-[11px] text-[var(--fg-4)]">{item.unit}</span>
      </div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="mb-1 block">
        <defs>
          <linearGradient id={`eg-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={item.accent} stopOpacity={0.35} />
            <stop offset="100%" stopColor={item.accent} stopOpacity={0} />
          </linearGradient>
        </defs>
        {item.kind === "bar" ? (
          values.map((v, i) => {
            const x = i * (W / values.length);
            const y = toY(v);
            const h = H - y;
            return (
              <rect
                key={i}
                x={x}
                y={y}
                width={barWidth}
                height={h}
                fill={item.accent}
                opacity={i === values.length - 1 ? 0.9 : 0.45}
                rx={1}
              />
            );
          })
        ) : (
          <>
            <polygon points={areaPoints} fill={`url(#eg-${uid})`} />
            <polyline
              points={linePoints}
              fill="none"
              stroke={item.accent}
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </>
        )}
      </svg>
      <div className="flex items-center gap-[3px]">
        <span className="text-[9px] text-[var(--fg-6)]">{item.deltaLabel}</span>
        <span className="fa-num text-[10px] font-semibold" style={{ color: deltaColor }}>{item.delta}</span>
      </div>
    </div>
  );
}

interface SentimentMetricsProps {
  sentiment: EventFlowSentimentItem[];
}

export function SentimentMetrics({ sentiment }: SentimentMetricsProps) {
  return (
    <FACard
      title={
        <div className="flex items-center gap-2">
          <Activity size={12} className="text-[var(--brand-hover)]" />
          <span>市场情绪与定价概览</span>
        </div>
      }
      eyebrow="情绪"
      accent="brand"
    >
      {sentiment.length === 0 ? (
        <FAEmptyState title="暂无情绪数据" description="当前时间范围内没有情绪指标数据。" className="p-4" />
      ) : (
        <div className="flex gap-2">
          {sentiment.map((item) => (
            <SentimentCard key={item.label} item={item} />
          ))}
        </div>
      )}
    </FACard>
  );
}
