import { GitMerge } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type { EventFlowChainStep, EventFlowTimelineItem, PricingStatus } from "@/types/event-flow";

const KIND_COLORS: Record<string, string> = {
  blue: "#60a5fa",
  warn: "#f59e0b",
  teal: "#06b6d4",
  up: "#10b981",
  down: "#f05252",
  grey: "#94a3b8",
  purp: "#a855f7",
};

const KIND_BG: Record<string, string> = {
  blue: "rgba(59,130,246,0.14)",
  warn: "rgba(245,158,11,0.14)",
  teal: "rgba(6,182,212,0.12)",
  up: "rgba(16,185,129,0.14)",
  down: "rgba(240,82,82,0.14)",
  grey: "rgba(148,163,184,0.10)",
  purp: "rgba(168,85,247,0.12)",
};

const KIND_BORDER: Record<string, string> = {
  blue: "rgba(59,130,246,0.30)",
  warn: "rgba(245,158,11,0.30)",
  teal: "rgba(6,182,212,0.28)",
  up: "rgba(16,185,129,0.32)",
  down: "rgba(240,82,82,0.32)",
  grey: "rgba(148,163,184,0.22)",
  purp: "rgba(168,85,247,0.28)",
};

const PRICING_COLOR: Record<string, string> = {
  "已定价": "#10b981",
  "部分定价": "#f59e0b",
  "未定价": "#f05252",
};

const PRICING_BG: Record<string, string> = {
  "已定价": "rgba(16,185,129,0.14)",
  "部分定价": "rgba(245,158,11,0.14)",
  "未定价": "rgba(240,82,82,0.14)",
};

const PRICING_BORDER: Record<string, string> = {
  "已定价": "rgba(16,185,129,0.32)",
  "部分定价": "rgba(245,158,11,0.30)",
  "未定价": "rgba(240,82,82,0.32)",
};

function extractStepNumber(num: string): string {
  const map: Record<string, string> = { "①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5", "⑥": "6" };
  return map[num] ?? num;
}

function ChainBox({ step }: { step: EventFlowChainStep }) {
  const color = KIND_COLORS[step.kind] ?? KIND_COLORS.grey;
  const bg = KIND_BG[step.kind] ?? KIND_BG.grey;
  const border = KIND_BORDER[step.kind] ?? KIND_BORDER.grey;
  const isPricing = Boolean(step.pricing);
  const pricingColor = step.pricing ? (PRICING_COLOR[step.pricing] ?? "#f59e0b") : "#f59e0b";
  const pricingBg = step.pricing ? (PRICING_BG[step.pricing] ?? "rgba(245,158,11,0.14)") : "";
  const pricingBorder = step.pricing ? (PRICING_BORDER[step.pricing] ?? "rgba(245,158,11,0.30)") : "";
  const R = 22;
  const circumference = 2 * Math.PI * R;

  return (
    <div
      className="flex min-w-[108px] flex-1 flex-col gap-[5px] rounded-[3px] border-t-2 px-[10px] py-[8px]"
      style={{
        background: "var(--bg-card-inner)",
        borderColor: color,
        borderLeft: "1px solid var(--border-faint)",
        borderRight: "1px solid var(--border-faint)",
        borderBottom: "1px solid var(--border-faint)",
      }}
    >
      <div className="flex items-center gap-[5px]">
        <span
          className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border text-[10px] font-bold"
          style={{ background: bg, borderColor: border, color }}
        >
          {extractStepNumber(step.num)}
        </span>
        <span className="text-[10px] font-semibold text-[var(--fg-3)]">{step.title}</span>
      </div>

      {isPricing ? (
        <div className="flex flex-col items-center gap-1">
          <svg width={52} height={52} viewBox="0 0 52 52">
            <circle cx={26} cy={26} r={R} fill="none" stroke="var(--border)" strokeWidth={7} />
            <circle
              cx={26}
              cy={26}
              r={R}
              fill="none"
              stroke={pricingColor}
              strokeWidth={7}
              strokeDasharray={`${circumference * 0.45} ${circumference * 0.55}`}
              strokeLinecap="round"
              transform="rotate(-90 26 26)"
            />
            <text
              x={26}
              y={30}
              textAnchor="middle"
              fontSize={9}
              fill={pricingColor}
              fontWeight="700"
              fontFamily="var(--font-mono)"
            >
              45%
            </text>
          </svg>
          {step.items.map((item, i) => (
            <div key={i} className="text-center text-[10px] leading-[1.4] text-[var(--fg-5)]">{item}</div>
          ))}
          {step.pricing ? (
            <span
              className="rounded-[3px] border px-2 py-[2px] text-[10px] font-semibold"
              style={{ background: pricingBg, borderColor: pricingBorder, color: pricingColor }}
            >
              {step.pricing}
            </span>
          ) : null}
        </div>
      ) : (
        step.items.map((item, i) => (
          <div
            key={i}
            className={`leading-[1.45] ${i === 0 ? "text-[11px] font-semibold text-[var(--fg-2)]" : "text-[10px] text-[var(--fg-5)]"}`}
          >
            {item}
          </div>
        ))
      )}
    </div>
  );
}

interface EventChainAnalysisProps {
  chain: EventFlowChainStep[];
  activeEvent: EventFlowTimelineItem | null;
}

export function EventChainAnalysis({ chain, activeEvent }: EventChainAnalysisProps) {
  if (chain.length === 0) {
    return (
      <FACard title="事件传导链分析" eyebrow="Chain" accent="brand">
        <FAEmptyState title="暂无传导链" description="当前事件没有传导链分析数据。" className="p-4" />
      </FACard>
    );
  }

  return (
    <FACard
      title={
        <div className="flex items-center gap-2">
          <GitMerge size={12} className="text-[var(--brand-hover)]" />
          <span>事件传导链分析</span>
        </div>
      }
      eyebrow="Event Chain"
      accent="brand"
      action={
        <div className="flex items-center gap-[10px]">
          {[
            { label: "已定价", color: "#10b981" },
            { label: "部分定价", color: "#f59e0b" },
            { label: "未定价", color: "#f05252" },
          ].map((item) => (
            <div key={item.label} className="flex items-center gap-[3px]">
              <span className="inline-block h-[6px] w-[6px] rounded-full" style={{ background: item.color }} />
              <span className="text-[10px] text-[var(--fg-5)]">{item.label}</span>
            </div>
          ))}
        </div>
      }
    >
      {activeEvent ? (
        <div className="mb-2 inline-flex items-center gap-2 rounded-[3px] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 py-1">
          <span className="text-[10px] text-[var(--fg-5)]">当前事件：</span>
          <span className="text-[10px] font-semibold text-[var(--brand-hover)]">{activeEvent.title}</span>
        </div>
      ) : null}

      <div className="flex items-stretch gap-0 overflow-x-auto" style={{ minHeight: 180 }}>
        {chain.map((step, i) => (
          <div key={step.num} className="flex items-stretch">
            <ChainBox step={step} />
            {i < chain.length - 1 ? (
              <div className="flex shrink-0 items-center px-[3px]">
                <span className="text-[13px] text-[var(--fg-6)]">&rsaquo;</span>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </FACard>
  );
}
