import { FACard } from "@/components/shared/FACard";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FATabBar, type FATabOption } from "@/components/shared/FATabBar";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { AgentPromptPanel } from "@/components/settings/AgentPromptPanel";
import { AgentRegistryPanel } from "@/components/settings/AgentRegistryPanel";
import { DataSourceSettingsPanel } from "@/components/settings/DataSourceSettingsPanel";
import { GeneralPreferencesPanel } from "@/components/settings/GeneralPreferencesPanel";
import { SecretSettingsPanel } from "@/components/settings/SecretSettingsPanel";
import { SettingsInfoRail } from "@/components/settings/SettingsInfoRail";
import type { SettingsDataSource } from "@/adapters/settings";
import type { SettingsTab, SettingsBannerState } from "@/hooks/useSettingsPage";
import type { useAgentRegistry } from "@/hooks/useAgentRegistry";
import type { useSettings } from "@/hooks/useSettings";

export const SETTINGS_TABS: FATabOption<SettingsTab>[] = [
  { value: "general", label: "通用设置" },
  { value: "datasource", label: "数据源接入" },
  { value: "api-key", label: "API 密钥" },
  { value: "agents", label: "Agent 管理" },
];

export function SettingsPageHeader({
  source,
  activeTab,
  onTabChange,
}: {
  source: string;
  activeTab: SettingsTab;
  onTabChange: (tab: SettingsTab) => void;
}) {
  return (
    <FACard
      title="设置"
      eyebrow="FinAnalytics Pro"
      accent="brand"
      action={<FAStatusPill tone="info">{source}</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      <FASectionHeader title="配置与接入" />
      <div className="flex justify-start">
        <FATabBar tabs={SETTINGS_TABS} value={activeTab} onChange={onTabChange} ariaLabel="设置分类" />
      </div>
    </FACard>
  );
}

export function SettingsPageBanner({ banner }: { banner: SettingsBannerState | null }) {
  return banner ? <FAWarningBanner title={banner.title} description={banner.description} tone={banner.tone} /> : null;
}

interface SettingsPageContentProps {
  activeTab: SettingsTab;
  data: NonNullable<ReturnType<typeof useSettings>["data"]>;
  preferences: Record<string, string>;
  setPreferences: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  isSavingPreferences: boolean;
  hasPreferenceChanges: boolean;
  onResetPreferences: () => void;
  onSavePreferences: () => void;
  savingSources: Record<string, boolean>;
  onToggleSource: (source: SettingsDataSource, next: boolean) => void;
  onResetSource: (source: SettingsDataSource) => void;
  secretSources: SettingsDataSource[];
  onSecretSaved: (message: string) => Promise<void>;
  onSecretError: (title: string, description: string) => void;
  agentRegistry: ReturnType<typeof useAgentRegistry>;
  selectedAgentId: string | null;
  setSelectedAgentId: React.Dispatch<React.SetStateAction<string | null>>;
  setBanner: React.Dispatch<React.SetStateAction<SettingsBannerState | null>>;
  historyEntries: any[];
  isHistoryLoading: boolean;
  historyError: string | null;
  rollingBackAuditId: string | null;
  onRollbackHistoryEntry: (entry: any) => Promise<void>;
}

export function SettingsPageContent({
  activeTab,
  data,
  preferences,
  setPreferences,
  isSavingPreferences,
  hasPreferenceChanges,
  onResetPreferences,
  onSavePreferences,
  savingSources,
  onToggleSource,
  onResetSource,
  secretSources,
  onSecretSaved,
  onSecretError,
  agentRegistry,
  selectedAgentId,
  setSelectedAgentId,
  setBanner,
  historyEntries,
  isHistoryLoading,
  historyError,
  rollingBackAuditId,
  onRollbackHistoryEntry,
}: SettingsPageContentProps) {
  return (
    <div className={activeTab === "agents" || activeTab === "general" ? "grid gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]" : ""}>
      <div className={activeTab === "agents" || activeTab === "general" ? "space-y-3" : ""}>
        {activeTab === "general" ? (
          <GeneralPreferencesPanel
            items={data.preferences}
            values={preferences}
            disabled={isSavingPreferences}
            hasChanges={hasPreferenceChanges}
            onReset={onResetPreferences}
            onSave={onSavePreferences}
            onChange={(key, next) => setPreferences((current) => ({ ...current, [key]: next }))}
          />
        ) : null}

        {activeTab === "datasource" ? (
          <DataSourceSettingsPanel
            sources={data.sources}
            savingSources={savingSources}
            onToggleSource={onToggleSource}
            onResetSource={onResetSource}
          />
        ) : null}

        {activeTab === "api-key" ? (
          <SecretSettingsPanel sources={secretSources} onSaved={onSecretSaved} onError={onSecretError} />
        ) : null}

        {activeTab === "agents" ? (
          <AgentRegistryPanel
            agents={agentRegistry.data?.agents ?? []}
            selectedAgentId={selectedAgentId}
            isLoading={agentRegistry.isLoading}
            isError={agentRegistry.isError}
            errorMessage={agentRegistry.error?.message}
            onSelectAgent={(agentId) => setSelectedAgentId(selectedAgentId === agentId ? null : agentId)}
          />
        ) : null}
      </div>

      {activeTab === "general" ? (
        <SettingsInfoRail
          systemInfo={data.systemInfo}
          globalConfig={data.globalConfig}
          historyEntries={historyEntries}
          isHistoryLoading={isHistoryLoading}
          historyError={historyError}
          rollingBackAuditId={rollingBackAuditId}
          onRollback={onRollbackHistoryEntry}
        />
      ) : activeTab === "agents" ? (
        <AgentPromptPanel
          agentId={selectedAgentId}
          agents={agentRegistry.data?.agents ?? []}
          onChanged={(title, description) => {
            setBanner({ tone: "info", title, description });
            agentRegistry.refetch();
          }}
          onError={(title, description) => setBanner({ tone: "down", title, description })}
        />
      ) : null}
    </div>
  );
}
