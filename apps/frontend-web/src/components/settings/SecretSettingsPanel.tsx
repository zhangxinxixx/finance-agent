import { useState } from "react";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { resetSettingsSecret, updateSettingsSecret } from "@/adapters/settings";
import type { SettingsDataSource } from "@/adapters/settings";
import { formatSettingsTime } from "./settingsFormat";

function SecretRow({
  source,
  onSaved,
  onError,
}: {
  source: SettingsDataSource;
  onSaved: (message: string) => void;
  onError: (title: string, description: string) => void;
}) {
  const [value, setValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleSave() {
    if (!value.trim()) return;
    setIsSaving(true);
    setMessage(null);
    try {
      await updateSettingsSecret(source.id, {
        secret_value: value.trim(),
        actor: "automation",
        reason: "settings page secret update",
        request_id: `settings-secret-${source.id}-${Date.now()}`,
      });
      setValue("");
      setMessage("已保存");
      onSaved(`${source.name} 密钥已保存`);
    } catch (cause) {
      const description = cause instanceof Error ? cause.message : "保存失败";
      setMessage(description);
      onError(`${source.name} 保存失败`, description);
    } finally {
      setIsSaving(false);
    }
  }

  async function handleReset() {
    setIsSaving(true);
    setMessage(null);
    try {
      await resetSettingsSecret(source.id, {
        actor: "automation",
        reason: "settings page secret reset",
        request_id: `settings-secret-reset-${source.id}-${Date.now()}`,
      });
      setValue("");
      setMessage("已清除");
      onSaved(`${source.name} 密钥已清除`);
    } catch (cause) {
      const description = cause instanceof Error ? cause.message : "清除失败";
      setMessage(description);
      onError(`${source.name} 清除失败`, description);
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold text-[var(--fg-2)]">{source.name}</div>
          <div className="mt-0.5 text-[10px] text-[var(--fg-5)]">{source.description}</div>
        </div>
        <div className="flex items-center gap-2">
          <span className="fa-num text-[10px] text-[var(--fg-3)]">{source.apiKeyMasked ?? "未配置"}</span>
          <FAStatusPill tone={source.secretConfigured ? "info" : "dim"}>
            {source.secretConfigured ? "CONFIGURED" : "UNCONFIGURED"}
          </FAStatusPill>
        </div>
      </div>
      {source.secretWritable ? (
        <div className="mt-2 flex items-center gap-2">
          <input
            type="password"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="输入新的 API Key"
            className="h-8 flex-1 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-panel)] px-2.5 text-[11px] text-[var(--fg-2)] outline-none placeholder:text-[var(--fg-5)]"
          />
          <button
            type="button"
            disabled={isSaving || !value.trim()}
            onClick={handleSave}
            className="inline-flex h-8 items-center rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] font-semibold text-[var(--fg-2)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            保存
          </button>
          <button
            type="button"
            disabled={isSaving || !source.secretConfigured}
            onClick={handleReset}
            className="inline-flex h-8 items-center rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] font-semibold text-[var(--fg-2)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            清除
          </button>
        </div>
      ) : null}
      <div className="mt-2 flex items-center justify-between gap-3 text-[10px] text-[var(--fg-5)]">
        <span>{source.secretLastUpdatedAt ? formatSettingsTime(source.secretLastUpdatedAt) : "未写入"}</span>
        {message ? <span className="text-[var(--fg-3)]">{message}</span> : null}
      </div>
    </div>
  );
}

interface SecretSettingsPanelProps {
  sources: SettingsDataSource[];
  onSaved: (message: string) => void;
  onError: (title: string, description: string) => void;
}

export function SecretSettingsPanel({ sources, onSaved, onError }: SecretSettingsPanelProps) {
  return (
    <FACard title="密钥状态" eyebrow="Encrypted Secret Storage" accent="warn" bodyClassName="space-y-2">
      {sources.map((source) => (
        <SecretRow key={source.id} source={source} onSaved={onSaved} onError={onError} />
      ))}
    </FACard>
  );
}
