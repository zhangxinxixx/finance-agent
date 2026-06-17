import type { KnowledgeItem, KnowledgeItemStatus } from "@/types/knowledge";

interface KnowledgeListItemProps {
  item: KnowledgeItem;
  isActive: boolean;
  onSelect: (id: string) => void;
}

const TYPE_ICON_CLASS: Record<string, string> = {
  method: "bg-[var(--info-soft)] text-[var(--info)]",
  playbook: "bg-[rgba(139,92,246,0.12)] text-[var(--chart-5)]",
  note: "bg-[var(--up-soft)] text-[var(--up)]",
  review: "bg-[var(--warn-soft)] text-[var(--warn)]",
  agent: "bg-[rgba(229,163,46,0.12)] text-[var(--chart-1)]",
  dict: "bg-[var(--down-soft)] text-[var(--down)]",
};

const TYPE_GLYPH: Record<string, string> = {
  method: "法",
  playbook: "▣",
  note: "记",
  review: "复",
  agent: "A",
  dict: "字",
};

const STATUS_TONE: Record<KnowledgeItemStatus, string> = {
  "长期有效": "border-[var(--up-border)] bg-[var(--up-soft)] text-[var(--up)]",
  "待复核": "border-[var(--warn-border)] bg-[var(--warn-soft)] text-[var(--warn)]",
  "阶段有效": "border-[rgba(139,92,246,0.25)] bg-[rgba(139,92,246,0.1)] text-[var(--chart-5)]",
};

const TAG_TONE: Record<string, string> = {
  gold: "border-[rgba(229,163,46,0.18)] bg-[rgba(229,163,46,0.08)] text-[var(--chart-1)]",
  cyan: "border-[var(--info-border)] bg-[var(--info-soft)] text-[var(--info)]",
  green: "border-[var(--up-border)] bg-[var(--up-soft)] text-[var(--up)]",
  orange: "border-[var(--warn-border)] bg-[var(--warn-soft)] text-[var(--warn)]",
  violet: "border-[rgba(139,92,246,0.25)] bg-[rgba(139,92,246,0.1)] text-[var(--chart-5)]",
  red: "border-[var(--down-border)] bg-[var(--down-soft)] text-[var(--down)]",
};

function tagTone(tag: string): string {
  if (["黄金", "期权墙位", "Prompt", "Market Odds"].includes(tag)) return TAG_TONE.gold;
  if (["CME", "实际利率", "宏观", "盘中策略"].includes(tag)) return TAG_TONE.cyan;
  if (["流动性", "研究笔记"].includes(tag)) return TAG_TONE.green;
  if (["地缘风险", "复盘"].includes(tag)) return TAG_TONE.orange;
  if (["Playbook", "剧本模板", "Agent规则", "智能体规则"].includes(tag)) return TAG_TONE.violet;
  if (["数据字典", "字段说明"].includes(tag)) return TAG_TONE.red;
  return TAG_TONE.gold;
}

export function KnowledgeListItem({ item, isActive, onSelect }: KnowledgeListItemProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(item.id)}
      className={`w-full rounded-[var(--radius-lg)] border p-3 text-left transition-all duration-[var(--dur-fast)] ${
        isActive
          ? "border-[var(--brand)] bg-[var(--brand-dim)] shadow-[0_0_0_1px_var(--brand)]"
          : "border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
      }`}
    >
      <div className="flex items-start gap-2.5">
        <span
          className={`flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[var(--radius-md)] text-[12px] font-bold ${TYPE_ICON_CLASS[item.type] ?? TYPE_ICON_CLASS.method}`}
        >
          {TYPE_GLYPH[item.type] ?? "?"}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] font-semibold leading-snug text-[var(--fg-2)]">{item.title}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <span className={`inline-flex items-center rounded-[var(--radius-pill)] px-1.5 py-0.5 text-[9px] font-semibold ${STATUS_TONE[item.status]}`}>
              {item.status}
            </span>
            <span className={`inline-flex items-center rounded-[var(--radius-pill)] border px-1.5 py-0.5 text-[9px] font-semibold ${tagTone(item.typeLabel)}`}>
              {item.typeLabel}
            </span>
            <span className={`inline-flex items-center rounded-[var(--radius-pill)] border px-1.5 py-0.5 text-[9px] font-semibold ${tagTone(item.topic)}`}>
              {item.topic}
            </span>
          </div>
        </div>
      </div>
      <div className="mt-2.5 flex items-center justify-between text-[10px] text-[var(--fg-5)]">
        <span>{item.agentReady ? "Agent 可用" : "仅人工使用"}</span>
        <span className="fa-num">引用 {item.citations} / {item.updated}</span>
      </div>
    </button>
  );
}
