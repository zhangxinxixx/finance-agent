import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { PlaybookTemplateVersion } from "@/types/playbook";

interface PlaybookTemplateListProps {
  items: PlaybookTemplateVersion[];
  selectedId: string | null;
  onSelect: (playbookId: string) => void;
}

function toneForStatus(status: string) {
  if (["published", "long_term", "长期有效"].includes(status)) return "up";
  if (["candidate", "draft", "待复核", "阶段有效"].includes(status)) return "warn";
  if (["deprecated", "archived"].includes(status)) return "down";
  return "neutral";
}

export function PlaybookTemplateList({ items, selectedId, onSelect }: PlaybookTemplateListProps) {
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <button
          key={item.playbook_id}
          type="button"
          onClick={() => onSelect(item.playbook_id)}
          className={`w-full rounded-[var(--radius-md)] border p-2.5 text-left transition-colors ${
            selectedId === item.playbook_id
              ? "border-[var(--brand)] bg-[var(--brand-dim)]"
              : "border-[var(--border)] bg-[var(--bg-card-inner)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
          }`}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[12px] font-semibold text-[var(--fg-2)]">{item.title}</div>
              <div className="mt-0.5 text-[10px] text-[var(--fg-4)]">
                <span className="fa-num">{item.playbook_id}</span> / <span className="fa-num">{item.version}</span>
              </div>
            </div>
            <FAStatusPill tone={toneForStatus(item.status)} dot={false}>{item.status}</FAStatusPill>
          </div>
          <p className="mt-2 line-clamp-2 text-[11px] leading-relaxed text-[var(--fg-4)]">{item.summary}</p>
        </button>
      ))}
    </div>
  );
}
