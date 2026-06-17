import { useEffect, useMemo, useState } from "react";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { fetchSettingsHistory, rollbackSettingsEvent, type SettingsHistoryEntry } from "@/adapters/settings";
import {
  SettingsAuditEventDetail,
  SettingsAuditEventList,
  SettingsAuditFilters,
  SettingsAuditSummary,
} from "@/components/settings/SettingsAuditPanels";

type AuditScopeFilter = "all" | "global" | "source" | "secret";
type AuditActionFilter = "all" | "set" | "reset" | "rollback";
type AuditWindowFilter = "all" | "1" | "7" | "30";

const SCOPE_OPTIONS: Array<{ value: AuditScopeFilter; label: string }> = [
  { value: "all", label: "全部范围" },
  { value: "global", label: "全局" },
  { value: "source", label: "数据源" },
  { value: "secret", label: "密钥" },
];

const ACTION_OPTIONS: Array<{ value: AuditActionFilter; label: string }> = [
  { value: "all", label: "全部动作" },
  { value: "set", label: "写入" },
  { value: "reset", label: "清除" },
  { value: "rollback", label: "回滚" },
];

const WINDOW_OPTIONS: Array<{ value: AuditWindowFilter; label: string }> = [
  { value: "all", label: "全部时间" },
  { value: "1", label: "近 24 小时" },
  { value: "7", label: "近 7 天" },
  { value: "30", label: "近 30 天" },
];

export function SettingsAuditPage() {
  const [scope, setScope] = useState<AuditScopeFilter>("all");
  const [action, setAction] = useState<AuditActionFilter>("all");
  const [actor, setActor] = useState("");
  const [settingKey, setSettingKey] = useState("");
  const [query, setQuery] = useState("");
  const [timeWindow, setTimeWindow] = useState<AuditWindowFilter>("all");
  const [selectedAuditId, setSelectedAuditId] = useState<string | null>(null);
  const [entries, setEntries] = useState<SettingsHistoryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rollingBackAuditId, setRollingBackAuditId] = useState<string | null>(null);

  const days = timeWindow === "all" ? undefined : Number(timeWindow);

  async function loadHistory() {
    setIsLoading(true);
    setError(null);
    try {
      const history = await fetchSettingsHistory({
        limit: 100,
        scope: scope === "all" ? undefined : scope,
        action: action === "all" ? undefined : action,
        actor: actor.trim() || undefined,
        settingKey: settingKey.trim() || undefined,
        query: query.trim() || undefined,
        days,
      });
      setEntries(history);
      setSelectedAuditId((current) => current && history.some((entry) => entry.auditId === current) ? current : history[0]?.auditId ?? null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法加载 Settings 审计历史");
      setEntries([]);
      setSelectedAuditId(null);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, action, actor, settingKey, query, timeWindow]);

  const selectedEntry = useMemo(
    () => entries.find((entry) => entry.auditId === selectedAuditId) ?? entries[0] ?? null,
    [entries, selectedAuditId],
  );

  const rollbackableCount = useMemo(
    () => entries.filter((entry) => entry.scope !== "secret" && entry.action !== "rollback" && Boolean(entry.auditId)).length,
    [entries],
  );

  async function handleRollback(entry: SettingsHistoryEntry) {
    if (!entry.auditId) return;
    setRollingBackAuditId(entry.auditId);
    setError(null);
    try {
      await rollbackSettingsEvent(entry.auditId, {
        actor: "codex",
        reason: `rollback ${entry.settingKey}`,
        request_id: `settings-audit-rollback-${entry.auditId}-${Date.now()}`,
      });
      await loadHistory();
      setSelectedAuditId(entry.auditId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "回滚失败");
    } finally {
      setRollingBackAuditId(null);
    }
  }

  if (isLoading && entries.length === 0) {
    return (
      <div className="finance-page-shell">
        <LoadingSkeleton variant="page" />
      </div>
    );
  }

  return (
    <div className="finance-page-shell">
      <div className="space-y-4">
        <SettingsAuditSummary
          entriesCount={entries.length}
          rollbackableCount={rollbackableCount}
          selectedAuditId={selectedEntry?.auditId ?? null}
          scopeLabel={scope === "all" ? "全部" : scope}
        />

        <SettingsAuditFilters
          query={query}
          onQueryChange={setQuery}
          settingKey={settingKey}
          onSettingKeyChange={setSettingKey}
          actor={actor}
          onActorChange={setActor}
          scope={scope}
          onScopeChange={(value) => setScope(value as AuditScopeFilter)}
          scopeOptions={SCOPE_OPTIONS}
          action={action}
          onActionChange={(value) => setAction(value as AuditActionFilter)}
          actionOptions={ACTION_OPTIONS}
          timeWindow={timeWindow}
          onTimeWindowChange={(value) => setTimeWindow(value as AuditWindowFilter)}
          timeWindowOptions={WINDOW_OPTIONS}
          onRefresh={() => void loadHistory()}
        />

        {error ? <FAWarningBanner title="Settings 审计页不可用" description={error} tone="down" /> : null}

        <div className="grid gap-4 xl:grid-cols-[minmax(320px,1.1fr)_minmax(380px,0.9fr)]">
          <SettingsAuditEventList
            entries={entries}
            selectedAuditId={selectedEntry?.auditId ?? null}
            onSelect={setSelectedAuditId}
          />

          <SettingsAuditEventDetail
            entry={selectedEntry}
            rollingBackAuditId={rollingBackAuditId}
            onRollback={(entry) => void handleRollback(entry)}
          />
        </div>
      </div>
    </div>
  );
}

export default SettingsAuditPage;
