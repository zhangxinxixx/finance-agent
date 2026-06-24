import {
  SettingsPageBanner,
  SettingsPageContent,
  SettingsPageHeader,
} from "@/components/settings/SettingsPageSections";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import {
  SettingsPageErrorState,
  SettingsPageLoadingState,
} from "@/components/settings/SettingsPageStates";
import { useSettingsPage } from "@/hooks/useSettingsPage";

export function SettingsPage() {
  const {
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
  } = useSettingsPage();

  const { data, isLoading, isError, error, refetch } = settings;

  if (isLoading && !data) {
    return <SettingsPageLoadingState />;
  }

  if (isError || !data) {
    return <SettingsPageErrorState message={error?.message ?? "未知错误"} onRetry={refetch} />;
  }

  return (
    <FAPageScaffold bodyClassName="fa-page-stack">
      <SettingsPageHeader source={data.source} activeTab={activeTab} onTabChange={setActiveTab} />
      <SettingsPageBanner banner={banner} />
      <SettingsPageContent
        activeTab={activeTab}
        data={data}
        preferences={preferences}
        setPreferences={setPreferences}
        isSavingPreferences={isSavingPreferences}
        hasPreferenceChanges={hasPreferenceChanges}
        onResetPreferences={handleResetPreferences}
        onSavePreferences={handleSavePreferences}
        savingSources={savingSources}
        onToggleSource={handleToggleSource}
        onResetSource={handleResetSource}
        secretSources={secretSources}
        onSecretSaved={handleSecretSaved}
        onSecretError={handleSecretError}
        agentRegistry={agentRegistry}
        selectedAgentId={selectedAgentId}
        setSelectedAgentId={setSelectedAgentId}
        setBanner={setBanner}
        historyEntries={historyEntries}
        isHistoryLoading={isHistoryLoading}
        historyError={historyError}
        rollingBackAuditId={rollingBackAuditId}
        onRollbackHistoryEntry={handleRollbackHistoryEntry}
      />
    </FAPageScaffold>
  );
}

export default SettingsPage;
