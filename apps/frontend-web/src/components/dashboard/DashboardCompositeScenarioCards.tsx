import { BookOpen } from "lucide-react";

type ScenarioTone = "warn" | "up" | "down";

const TONE_COLOR: Record<ScenarioTone, string> = {
  warn: "var(--warn)",
  up: "var(--up)",
  down: "var(--down)",
};

const TONE_BORDER: Record<ScenarioTone, string> = {
  warn: "var(--warn-border)",
  up: "var(--up-border)",
  down: "var(--down-border)",
};

interface ScriptItem {
  tag: string;
  title: string;
  tone: ScenarioTone;
  trigger: string;
  target: string;
  invalid: string;
  rr: string;
}

const scripts: ScriptItem[] = [
  {
    tag: "主方案",
    title: "区间拉锯",
    tone: "warn",
    trigger: "4500 上方震荡，未有效跌破",
    target: "4575 / 4600",
    invalid: "跌破 4450",
    rr: "1:1.4",
  },
  {
    tag: "备选一",
    title: "转强突破",
    tone: "up",
    trigger: "有效站稳 4600 且回踩不破",
    target: "4650 / 4700",
    invalid: "跌回 4600 下方",
    rr: "1:2.2",
  },
  {
    tag: "备选二",
    title: "反转做空",
    tone: "down",
    trigger: "跌破 4500 且回抽失败",
    target: "4450 / 4400 / 4300",
    invalid: "重新站回 4500",
    rr: "1:2.4",
  },
];

export function DashboardCompositeScenarioCards() {
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5">
        <BookOpen size={12} className="text-[var(--brand-hover)]" />
        <span className="text-[12px] font-semibold leading-none text-[var(--fg-2)]">交易剧本</span>
        <span className="text-[10px] text-[var(--fg-5)]">主方案 + 2 备选</span>
      </div>
      <div className="dashboard-composite-scenario-grid">
        {scripts.map((script) => {
          const color = TONE_COLOR[script.tone];
          const borderColor = TONE_BORDER[script.tone];
          return (
            <div
              key={script.tag}
              className="relative overflow-hidden rounded-[var(--radius-lg)] bg-[var(--bg-card-inner)] p-3 transition-colors hover:bg-[var(--bg-hover)]"
              style={{ border: `1px solid ${borderColor}` }}
            >
              <div className="absolute inset-y-0 left-0 w-[3px]" style={{ background: color }} />
              <div className="mb-1.5 flex items-baseline justify-between pl-1.5">
                <span className="rounded-[var(--radius-pill)] px-2 py-0.5 text-[9px] font-bold leading-[1.3]" style={{ color, background: `color-mix(in srgb, ${color} 12%, transparent)` }}>{script.tag}</span>
                <span className="fa-compact-meta">
                  R:R <span className="fa-num text-[var(--fg-3)]">{script.rr}</span>
                </span>
              </div>
              <div className="mb-3 pl-1.5 text-[12px] font-bold leading-[1.3] text-[var(--fg-1)]">{script.title}</div>
              <div className="grid gap-2 pl-1.5">
                {[
                  { label: "触发条件", value: script.trigger },
                  { label: "目标位", value: script.target },
                  { label: "失效条件", value: script.invalid },
                ].map((field) => (
                  <div key={field.label} className="grid grid-cols-[54px_1fr] items-start gap-2">
                    <div className="fa-compact-meta">{field.label}</div>
                    <div className="text-[10px] leading-[1.5] text-[var(--fg-3)]">{field.value}</div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
