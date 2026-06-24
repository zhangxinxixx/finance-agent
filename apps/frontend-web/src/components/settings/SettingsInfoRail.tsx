import type { GlobalConfigItem, SettingsHistoryEntry, SystemInfoItem } from "@/adapters/settings";
import { SettingsHistoryCard } from "./SettingsHistoryCard";
import { SettingsSystemCard } from "./SettingsSystemCard";

interface SettingsInfoRailProps {
  systemInfo: SystemInfoItem[];
  globalConfig: GlobalConfigItem[];
  historyEntries: SettingsHistoryEntry[];
  isHistoryLoading: boolean;
  historyError: string | null;
  rollingBackAuditId: string | null;
  onRollback: (entry: SettingsHistoryEntry) => void;
}

export function SettingsInfoRail({
  systemInfo,
  globalConfig,
  historyEntries,
  isHistoryLoading,
  historyError,
  rollingBackAuditId,
  onRollback,
}: SettingsInfoRailProps) {
  return (
    <div className="space-y-3">
      <SettingsSystemCard title="系统信息" eyebrow="System" items={systemInfo} />
      <SettingsSystemCard title="环境路径" eyebrow="Infra" items={globalConfig} />
      <SettingsHistoryCard
        entries={historyEntries}
        isLoading={isHistoryLoading}
        error={historyError}
        rollingBackAuditId={rollingBackAuditId}
        onRollback={onRollback}
      />
    </div>
  );
}
