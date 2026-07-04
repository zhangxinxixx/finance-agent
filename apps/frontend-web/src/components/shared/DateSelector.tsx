import type { UnifiedDate } from "@/types/dashboard";
import { CalendarDays } from "lucide-react";

interface DateSelectorProps {
  dates: UnifiedDate[];
  selectedDate: string | null;
  generatedAt?: string | null;
  onChange: (date: string) => void;
}

export function DateSelector({ dates, selectedDate, generatedAt, onChange }: DateSelectorProps) {
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
      <label className="flex min-w-0 items-center gap-2 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2">
        <CalendarDays size={12} className="text-[var(--brand-hover)]" />
        <span className="fa-compact-label">交易日期</span>
        <select
          className="min-w-[9rem] bg-transparent text-[11px] font-medium text-[var(--fg-2)] outline-none"
          value={selectedDate ?? ""}
          onChange={(event) => onChange(event.target.value)}
        >
          {dates.map((date) => (
            <option key={date.trade_date} value={date.trade_date}>
              {date.trade_date}
            </option>
          ))}
        </select>
      </label>

      <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2">
        <div className="fa-compact-label">生成时间</div>
        <div className="fa-num mt-1 text-[11px] text-[var(--fa-text-muted)]">{generatedAt ?? "不可用"}</div>
      </div>
    </div>
  );
}
