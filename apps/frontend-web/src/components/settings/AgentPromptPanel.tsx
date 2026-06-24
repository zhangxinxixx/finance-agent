import { useState } from "react";
import { FACard } from "@/components/shared/FACard";
import {
  activateAgentPromptVersion,
  createAgentPromptFeedback,
  createAgentPromptVersion,
} from "@/adapters/agentRegistry";
import type { AgentRegistryItem, PromptVersionItem } from "@/types/agent-registry";
import { promptTemplatePayload, promptTemplateText } from "./agentPromptFormat";
import { AgentPromptFeedbackForm } from "./AgentPromptFeedbackForm";
import { AgentPromptFeedbackHistory } from "./AgentPromptFeedbackHistory";
import { AgentPromptEmptyState, AgentPromptSummary } from "./AgentPromptSummary";
import { AgentPromptVersionPanel } from "./AgentPromptVersionPanel";
import { useAgentPromptFeedbackHistory, useAgentPromptVersions } from "./useAgentPromptResources";

interface AgentPromptPanelProps {
  agentId: string | null;
  agents: AgentRegistryItem[];
  onChanged: (title: string, description?: string) => void;
  onError: (title: string, description: string) => void;
}

export function AgentPromptPanel({ agentId, agents, onChanged, onError }: AgentPromptPanelProps) {
  const agent = agents.find((a) => a.agent_id === agentId);
  const [isWritingPrompt, setIsWritingPrompt] = useState(false);
  const [activatingVersion, setActivatingVersion] = useState<string | null>(null);
  const [feedbackRating, setFeedbackRating] = useState("3");
  const [feedbackCategory, setFeedbackCategory] = useState("prompt_quality");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);
  const { versions, versionsNote, isLoadingVersions, reloadVersions } = useAgentPromptVersions(agentId);
  const { feedbackHistory, isFeedbackHistoryLoading, feedbackHistoryError, reloadFeedbackHistory } =
    useAgentPromptFeedbackHistory(agentId);

  if (!agent) {
    return <AgentPromptEmptyState />;
  }

  const selectedAgent = agent;
  const promptText = promptTemplateText(selectedAgent.prompt);
  const pv = selectedAgent.prompt_version;

  async function handleCreateDraft() {
    const prompt_template = promptTemplatePayload(selectedAgent.prompt);
    if (Object.keys(prompt_template).length === 0) {
      onError("Prompt 模板为空", "当前 Agent registry 未提供可同步的 Prompt 模板。");
      return;
    }
    setIsWritingPrompt(true);
    try {
      const version = await createAgentPromptVersion(selectedAgent.agent_id, {
        prompt_kind: selectedAgent.prompt?.kind ?? "llm",
        prompt_source: selectedAgent.prompt?.source ?? selectedAgent.source_module,
        prompt_template,
        status: "draft",
        enabled: true,
        change_note: "settings page synced registry prompt template",
        created_by: "automation",
        request_id: `settings-prompt-${selectedAgent.agent_id}-${Date.now()}`,
      });
      await reloadVersions();
      onChanged("Prompt 草稿已创建", `${selectedAgent.name} 已创建 ${version.version}，历史 AgentOutput 未被修改。`);
    } catch (cause) {
      onError("创建 Prompt 草稿失败", cause instanceof Error ? cause.message : "无法写入 prompt_versions");
    } finally {
      setIsWritingPrompt(false);
    }
  }

  async function handleActivate(version: PromptVersionItem) {
    setActivatingVersion(version.version);
    try {
      const active = await activateAgentPromptVersion(selectedAgent.agent_id, {
        version: version.version,
        reason: "settings page activation",
      });
      await reloadVersions();
      onChanged("Prompt 版本已激活", `${selectedAgent.name} 当前激活版本为 ${active.version}，历史运行继续指向原版本。`);
    } catch (cause) {
      onError("激活 Prompt 版本失败", cause instanceof Error ? cause.message : "无法激活 prompt version");
    } finally {
      setActivatingVersion(null);
    }
  }

  async function handleSubmitFeedback() {
    if (!feedbackComment.trim()) {
      onError("反馈内容为空", "请填写需要修正或复核的 Prompt / 输出问题。");
      return;
    }
    setIsSubmittingFeedback(true);
    try {
      await createAgentPromptFeedback({
        agent_id: selectedAgent.agent_id,
        prompt_version_id: pv?.id,
        rating: Number(feedbackRating),
        category: feedbackCategory,
        comment: feedbackComment.trim(),
        submitted_by: "automation",
        request_id: `settings-feedback-${selectedAgent.agent_id}-${Date.now()}`,
      });
      await reloadFeedbackHistory();
      setFeedbackComment("");
      onChanged("反馈已提交", "反馈已追加到 Prompt Feedback，不会修改历史 AgentOutput。");
    } catch (cause) {
      onError("反馈提交失败", cause instanceof Error ? cause.message : "无法写入 prompt_feedback");
    } finally {
      setIsSubmittingFeedback(false);
    }
  }

  return (
    <FACard title="Prompt 详情" eyebrow={agent.name} accent="brand" bodyClassName="space-y-3">
      <AgentPromptSummary agent={agent} promptText={promptText} />

      <AgentPromptVersionPanel
        versions={versions}
        versionsNote={versionsNote}
        isLoading={isLoadingVersions}
        isWritingPrompt={isWritingPrompt}
        activatingVersion={activatingVersion}
        onCreateDraft={handleCreateDraft}
        onActivate={handleActivate}
      />

      <AgentPromptFeedbackForm
        rating={feedbackRating}
        category={feedbackCategory}
        comment={feedbackComment}
        isSubmitting={isSubmittingFeedback}
        onRatingChange={setFeedbackRating}
        onCategoryChange={setFeedbackCategory}
        onCommentChange={setFeedbackComment}
        onSubmit={handleSubmitFeedback}
      />

      <AgentPromptFeedbackHistory
        feedbackHistory={feedbackHistory}
        isLoading={isFeedbackHistoryLoading}
        error={feedbackHistoryError}
      />
    </FACard>
  );
}
