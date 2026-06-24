import { BarChart3, BookOpen, FileText, Landmark, LineChart, Newspaper, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { sourceStatusTone } from "@/adapters/settings";
import type { SettingsDataSource } from "@/adapters/settings";

const ICON_MAP: Record<string, LucideIcon> = {
  BarChart3,
  LineChart,
  Newspaper,
  TrendingUp,
  Landmark,
  BookOpen,
  FileText,
};

function resolveIcon(iconName: string): LucideIcon {
  return ICON_MAP[iconName] ?? BarChart3;
}

function Toggle({
  enabled,
  disabled,
  onChange,
}: {
  enabled: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      disabled={disabled}
      onClick={() => onChange(!enabled)}
      className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-[var(--radius-pill)] border transition-colors ${
        enabled ? "border-[var(--up-border)] bg-[var(--up-soft)]" : "border-[var(--border)] bg-[var(--bg-panel)]"
      } ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
    >
      <span
        className={`inline-block h-2.5 w-2.5 rounded-[var(--radius-pill)] transition-transform ${
          enabled ? "translate-x-[13px] bg-[var(--up)]" : "translate-x-[3px] bg-[var(--fg-5)]"
        }`}
      />
    </button>
  );
}

function SourceCard({
  source,
  saving,
  onToggleChange,
  onReset,
}: {
  source: SettingsDataSource;
  saving: boolean;
  onToggleChange: (next: boolean) => void;
  onReset: () => void;
}) {
  const Icon = resolveIcon(source.icon);

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex items-center gap-2">
        <div
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-md)]"
          style={{ background: `${source.color}22`, color: source.color }}
        >
          <Icon size={14} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] font-semibold text-[var(--fg-2)]">{source.name}</div>
          <div className="mt-0.5 truncate text-[9px] text-[var(--fg-5)]">{source.description}</div>
        </div>
        <Toggle enabled={source.enabled} disabled={saving} onChange={onToggleChange} />
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 border-t border-[var(--border)] pt-2">
        <span className="text-[10px] text-[var(--fg-5)]">请求状态</span>
        <FAStatusPill tone={source.enabled ? "info" : "dim"}>{source.enabled ? "ENABLED" : "DISABLED"}</FAStatusPill>
      </div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="text-[10px] text-[var(--fg-5)]">运行状态</span>
        <FAStatusPill tone={sourceStatusTone(source)}>{source.status}</FAStatusPill>
      </div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="text-[10px] text-[var(--fg-5)]">API Key</span>
        <span className="fa-num text-[10px] text-[var(--fg-3)]">{source.apiKeyMasked ?? "未配置"}</span>
      </div>
      {source.isOverridden ? (
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            disabled={saving}
            onClick={onReset}
            className="text-[10px] font-semibold text-[var(--brand)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            清除覆盖
          </button>
        </div>
      ) : null}
    </div>
  );
}

interface DataSourceSettingsPanelProps {
  sources: SettingsDataSource[];
  savingSources: Record<string, boolean>;
  onToggleSource: (source: SettingsDataSource, next: boolean) => void;
  onResetSource: (source: SettingsDataSource) => void;
}

export function DataSourceSettingsPanel({
  sources,
  savingSources,
  onToggleSource,
  onResetSource,
}: DataSourceSettingsPanelProps) {
  return (
    <FACard title="接入与连接状态" eyebrow="数据源" accent="brand" bodyClassName="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {sources.map((source) => (
          <SourceCard
            key={source.id}
            source={source}
            saving={Boolean(savingSources[source.id])}
            onToggleChange={(next) => onToggleSource(source, next)}
            onReset={() => onResetSource(source)}
          />
        ))}
      </div>
    </FACard>
  );
}
