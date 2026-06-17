import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { PromptVersionItem } from "@/types/agent-registry";
import { formatPromptVersionTime } from "./agentPromptFormat";

interface AgentPromptVersionPanelProps {
  versions: PromptVersionItem[];
  versionsNote: string | null;
  isLoading: boolean;
  isWritingPrompt: boolean;
  activatingVersion: string | null;
  onCreateDraft: () => void;
  onActivate: (version: PromptVersionItem) => void;
}

export function AgentPromptVersionPanel({
  versions,
  versionsNote,
  isLoading,
  isWritingPrompt,
  activatingVersion,
  onCreateDraft,
  onActivate,
}: AgentPromptVersionPanelProps) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)]">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--border-faint)] px-2.5 py-2">
        <div>
          <div className="text-[12px] font-semibold text-[var(--fg-2)]">版本治理</div>
          <div className="mt-0.5 text-[11px] text-[var(--fg-4)]">Prompt 修改只创建新版本，不覆盖历史运行。</div>
        </div>
        <button
          type="button"
          disabled={isWritingPrompt}
          onClick={onCreateDraft}
          className="inline-flex h-8 shrink-0 items-center rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isWritingPrompt ? "同步中..." : "同步草稿"}
        </button>
      </div>
      <div className="space-y-2 p-2.5">
        {versionsNote ? <div className="text-[11px] text-[var(--fg-4)]">{versionsNote}</div> : null}
        {isLoading ? <div className="text-[11px] text-[var(--fg-4)]">加载版本...</div> : null}
        {!isLoading && versions.length === 0 && !versionsNote ? (
          <div className="text-[11px] text-[var(--fg-4)]">暂无持久化版本。</div>
        ) : null}
        {versions.map((version) => (
          <div key={version.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <FAStatusPill tone={version.status === "active" ? "info" : "dim"} className="text-[12px]">{version.version}</FAStatusPill>
                <FAStatusPill tone={version.enabled ? "neutral" : "down"} className="text-[12px]">
                  {version.status === "active" ? "激活" : version.status}
                </FAStatusPill>
                <span className="truncate text-[11px] text-[var(--fg-4)]">{version.change_note ?? version.prompt_source ?? "无备注"}</span>
              </div>
              <button
                type="button"
                disabled={version.status === "active" || activatingVersion === version.version}
                onClick={() => onActivate(version)}
                className="inline-flex h-7 shrink-0 items-center rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-2.5 text-[10px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {activatingVersion === version.version ? "激活中..." : "激活"}
              </button>
            </div>
            <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-[var(--fg-5)]">
              <span className="font-mono">{version.prompt_sha256.slice(0, 12)}</span>
              <span>{formatPromptVersionTime(version.updated_at ?? version.created_at)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
