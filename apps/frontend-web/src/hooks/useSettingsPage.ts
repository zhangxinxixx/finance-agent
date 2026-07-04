import { useEffect, useMemo, useState } from "react";
import { useAgentRegistry } from "@/hooks/useAgentRegistry";
import { useSettings } from "@/hooks/useSettings";
import {
  fetchSettingsHistory,
  resetSettingsPreferences,
  resetSettingsSource,
  rollbackSettingsEvent,
  updateSettingsPreferences,
  updateSettingsSource,
} from "@/adapters/settings";
import type { SettingsDataSource, SettingsHistoryEntry } from "@/adapters/settings";

export type SettingsTab = "general" | "datasource" | "api-key" | "agents";

export interface SettingsBannerState {
  tone: "info" | "down";
  title: string;
  description?: string;
}

export function useSettingsPage() {
  const settings = useSettings();
  const agentRegistry = useAgentRegistry();
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [preferences, setPreferences] = useState<Record<string, string>>({});
  const [isSavingPreferences, setIsSavingPreferences] = useState(false);
  const [savingSources, setSavingSources] = useState<Record<string, boolean>>({});
  const [banner, setBanner] = useState<SettingsBannerState | null>(null);
  const [historyEntries, setHistoryEntries] = useState<SettingsHistoryEntry[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [rollingBackAuditId, setRollingBackAuditId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  useEffect(() => {
    if (!settings.data) return;
    setPreferences(Object.fromEntries(settings.data.preferences.map((item) => [item.key, item.value])));
  }, [settings.data]);

  useEffect(() => {
    void loadHistory();
  }, []);

  const hasPreferenceChanges = useMemo(() => {
    if (!settings.data) return false;
    return settings.data.preferences.some((item) => (preferences[item.key] ?? item.value) !== item.value);
  }, [preferences, settings.data]);

  const secretSources = useMemo(
    () => settings.data?.sources.filter((source) => source.secretWritable) ?? [],
    [settings.data],
  );

  async function loadHistory() {
    setIsHistoryLoading(true);
    setHistoryError(null);
    try {
      const entries = await fetchSettingsHistory();
      setHistoryEntries(entries);
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "无法加载设置历史");
    } finally {
      setIsHistoryLoading(false);
    }
  }

  async function handleSavePreferences() {
    if (!settings.data) return;
    setIsSavingPreferences(true);
    setBanner(null);
    try {
      await updateSettingsPreferences({
        language: preferences.language,
        timezone: preferences.timezone,
        report_template: preferences.report_template,
        actor: "codex",
        reason: "settings page preference update",
        request_id: `settings-pref-${Date.now()}`,
      });
      setBanner({ tone: "info", title: "全局偏好已保存", description: "语言、时区和报告模板已写入可审计配置层。" });
      settings.refetch();
      void loadHistory();
    } catch (cause) {
      setBanner({
        tone: "down",
        title: "保存失败",
        description: cause instanceof Error ? cause.message : "无法写入全局偏好配置",
      });
    } finally {
      setIsSavingPreferences(false);
    }
  }

  async function handleResetPreferences() {
    setIsSavingPreferences(true);
    setBanner(null);
    try {
      await resetSettingsPreferences({
        keys: ["language", "timezone", "report_template"],
        actor: "codex",
        reason: "reset settings preferences to defaults",
        request_id: `settings-pref-reset-${Date.now()}`,
      });
      setBanner({ tone: "info", title: "已恢复默认偏好", description: "全局偏好已回退到默认值。" });
      settings.refetch();
      void loadHistory();
    } catch (cause) {
      setBanner({
        tone: "down",
        title: "恢复默认失败",
        description: cause instanceof Error ? cause.message : "无法回退全局偏好配置",
      });
    } finally {
      setIsSavingPreferences(false);
    }
  }

  async function handleToggleSource(source: SettingsDataSource, next: boolean) {
    setSavingSources((current) => ({ ...current, [source.id]: true }));
    setBanner(null);
    try {
      await updateSettingsSource(source.id, {
        enabled: next,
        actor: "codex",
        reason: "settings page source toggle",
        request_id: `settings-source-${source.id}-${Date.now()}`,
      });
      setBanner({
        tone: "info",
        title: `${source.name} 已更新`,
        description: `数据源请求状态已切换为 ${next ? "enabled" : "disabled"}。`,
      });
      settings.refetch();
      void loadHistory();
    } catch (cause) {
      setBanner({
        tone: "down",
        title: `${source.name} 更新失败`,
        description: cause instanceof Error ? cause.message : "无法写入数据源请求状态",
      });
    } finally {
      setSavingSources((current) => ({ ...current, [source.id]: false }));
    }
  }

  async function handleResetSource(source: SettingsDataSource) {
    setSavingSources((current) => ({ ...current, [source.id]: true }));
    setBanner(null);
    try {
      await resetSettingsSource(source.id, {
        actor: "codex",
        reason: "clear source enable override",
        request_id: `settings-source-reset-${source.id}-${Date.now()}`,
      });
      setBanner({
        tone: "info",
        title: `${source.name} 已清除覆盖`,
        description: "该数据源已回退到默认检测状态。",
      });
      settings.refetch();
      void loadHistory();
    } catch (cause) {
      setBanner({
        tone: "down",
        title: `${source.name} 清除覆盖失败`,
        description: cause instanceof Error ? cause.message : "无法清除数据源覆盖状态",
      });
    } finally {
      setSavingSources((current) => ({ ...current, [source.id]: false }));
    }
  }

  async function handleRollbackHistoryEntry(entry: SettingsHistoryEntry) {
    if (!entry.auditId) return;
    setRollingBackAuditId(entry.auditId);
    setBanner(null);
    try {
      await rollbackSettingsEvent(entry.auditId, {
        actor: "codex",
        reason: `rollback ${entry.settingKey}`,
        request_id: `settings-rollback-${entry.auditId}-${Date.now()}`,
      });
      setBanner({
        tone: "info",
        title: "配置已回滚",
        description: `${entry.settingKey} 已按历史事件恢复。`,
      });
      settings.refetch();
      await loadHistory();
    } catch (cause) {
      setBanner({
        tone: "down",
        title: "回滚失败",
        description: cause instanceof Error ? cause.message : "无法回滚历史配置",
      });
    } finally {
      setRollingBackAuditId(null);
    }
  }

  async function handleSecretSaved(message: string) {
    setBanner({
      tone: "info",
      title: message,
      description: "密钥已写入加密配置层，状态页仅返回脱敏元数据。",
    });
    settings.refetch();
    await loadHistory();
  }

  function handleSecretError(title: string, description: string) {
    setBanner({
      tone: "down",
      title,
      description,
    });
  }

  return {
    settings,
    agentRegistry,
    activeTab,
    setActiveTab,
    preferences,
    setPreferences,
    isSavingPreferences,
    savingSources,
    banner,
    setBanner,
    historyEntries,
    isHistoryLoading,
    historyError,
    rollingBackAuditId,
    selectedAgentId,
    setSelectedAgentId,
    hasPreferenceChanges,
    secretSources,
    handleSavePreferences,
    handleResetPreferences,
    handleToggleSource,
    handleResetSource,
    handleRollbackHistoryEntry,
    handleSecretSaved,
    handleSecretError,
  };
}
