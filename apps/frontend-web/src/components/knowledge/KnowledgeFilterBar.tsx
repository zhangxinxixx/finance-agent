import { Search } from "lucide-react";
import { FAFilterBar } from "@/components/shared/FAFilterBar";

interface KnowledgeFilterBarProps {
  search: string;
  onSearchChange: (value: string) => void;
  topic: string;
  topics: string[];
  onTopicChange: (value: string) => void;
  status: string;
  statuses: string[];
  onStatusChange: (value: string) => void;
}

export function KnowledgeFilterBar({
  search,
  onSearchChange,
  topic,
  topics,
  onTopicChange,
  status,
  statuses,
  onStatusChange,
}: KnowledgeFilterBarProps) {
  return (
    <FAFilterBar
      className="knowledge-filter-bar"
      left={
        <>
          <div className="relative min-w-0 flex-1">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--fg-5)]" />
            <input
              type="text"
              value={search}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="搜索主题、规则、输入数据、引用模块"
              className="w-full rounded-full border border-[var(--border)] bg-[var(--bg-card)] py-2 pl-8 pr-3 text-[12px] text-[var(--fg-2)] placeholder:text-[var(--fg-5)] focus:border-[var(--brand)] focus:outline-none"
            />
          </div>
          <FilterChipGroup
            label="主题"
            value={topic}
            options={topics}
            onChange={onTopicChange}
          />
          <div className="h-4 w-px bg-[var(--border)]" />
          <FilterChipGroup
            label="状态"
            value={status}
            options={statuses}
            onChange={onStatusChange}
          />
        </>
      }
    />
  );
}

interface FilterChipGroupProps {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}

function FilterChipGroup({ label, value, options, onChange }: FilterChipGroupProps) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</span>
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          className={`rounded-[var(--radius-pill)] border px-2 py-0.5 text-[10px] font-semibold transition-colors ${
            value === option
              ? "border-[var(--brand)] bg-[var(--bg-active)] text-[var(--brand-hover)]"
              : "border-[var(--border)] bg-[var(--bg-card)] text-[var(--fg-4)] hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
