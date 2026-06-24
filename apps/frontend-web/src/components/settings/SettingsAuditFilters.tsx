import { Clock3, RefreshCw, Search } from "lucide-react";
import { FAFilterBar } from "@/components/shared/FAFilterBar";

function SelectPill({
  label,
  value,
  options,
  onChange,
  minWidth,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
  minWidth: string;
}) {
  return (
    <label className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] text-[var(--fg-4)]">
      <span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="bg-transparent text-[11px] text-[var(--fg-2)] outline-none"
        style={{ minWidth }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} className="bg-[var(--bg-card)] text-[var(--fg-2)]">
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function SettingsAuditFilters({
  query,
  onQueryChange,
  settingKey,
  onSettingKeyChange,
  actor,
  onActorChange,
  scope,
  onScopeChange,
  scopeOptions,
  action,
  onActionChange,
  actionOptions,
  timeWindow,
  onTimeWindowChange,
  timeWindowOptions,
  onRefresh,
}: {
  query: string;
  onQueryChange: (value: string) => void;
  settingKey: string;
  onSettingKeyChange: (value: string) => void;
  actor: string;
  onActorChange: (value: string) => void;
  scope: string;
  onScopeChange: (value: string) => void;
  scopeOptions: Array<{ value: string; label: string }>;
  action: string;
  onActionChange: (value: string) => void;
  actionOptions: Array<{ value: string; label: string }>;
  timeWindow: string;
  onTimeWindowChange: (value: string) => void;
  timeWindowOptions: Array<{ value: string; label: string }>;
  onRefresh: () => void;
}) {
  return (
    <FAFilterBar
      left={
        <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] text-[var(--fg-4)]">
            <Search size={12} />
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="搜索原因 / audit_id / request_id"
              className="w-[220px] bg-transparent text-[11px] text-[var(--fg-2)] outline-none placeholder:text-[var(--fg-5)]"
            />
          </label>
          <label className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] text-[var(--fg-4)]">
            <span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">键</span>
            <input
              value={settingKey}
              onChange={(event) => onSettingKeyChange(event.target.value)}
              placeholder="global.language"
              className="w-[160px] bg-transparent text-[11px] text-[var(--fg-2)] outline-none placeholder:text-[var(--fg-5)]"
            />
          </label>
          <label className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] text-[var(--fg-4)]">
            <span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">Actor</span>
            <input
              value={actor}
              onChange={(event) => onActorChange(event.target.value)}
              placeholder="automation"
              className="w-[110px] bg-transparent text-[11px] text-[var(--fg-2)] outline-none placeholder:text-[var(--fg-5)]"
            />
          </label>
          <SelectPill label="范围" value={scope} options={scopeOptions} onChange={onScopeChange} minWidth="100px" />
          <SelectPill label="动作" value={action} options={actionOptions} onChange={onActionChange} minWidth="100px" />
          <label className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] text-[var(--fg-4)]">
            <Clock3 size={12} />
            <select
              value={timeWindow}
              onChange={(event) => onTimeWindowChange(event.target.value)}
              className="min-w-[120px] bg-transparent text-[11px] text-[var(--fg-2)] outline-none"
            >
              {timeWindowOptions.map((option) => (
                <option key={option.value} value={option.value} className="bg-[var(--bg-card)] text-[var(--fg-2)]">
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      }
      right={
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3.5 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
        >
          <RefreshCw size={12} />
          刷新
        </button>
      }
    />
  );
}
