import { useEffect, useState } from "react";
import { fetchAgentPromptFeedback, fetchAgentPromptVersions } from "@/adapters/agentRegistry";
import type { PromptFeedbackItem, PromptVersionItem } from "@/types/agent-registry";

interface AgentPromptVersionsState {
  versions: PromptVersionItem[];
  versionsNote: string | null;
  isLoadingVersions: boolean;
  reloadVersions: () => Promise<void>;
}

interface AgentPromptFeedbackHistoryState {
  feedbackHistory: PromptFeedbackItem[];
  isFeedbackHistoryLoading: boolean;
  feedbackHistoryError: string | null;
  reloadFeedbackHistory: () => Promise<void>;
}

async function loadPromptVersions(agentId: string) {
  const response = await fetchAgentPromptVersions(agentId);
  return {
    versions: response.versions,
    versionsNote: response.note ?? null,
  };
}

async function loadPromptFeedbackHistory(agentId: string) {
  const response = await fetchAgentPromptFeedback({ agentId, limit: 8 });
  return response.feedback;
}

export function useAgentPromptVersions(agentId: string | null): AgentPromptVersionsState {
  const [versions, setVersions] = useState<PromptVersionItem[]>([]);
  const [versionsNote, setVersionsNote] = useState<string | null>(null);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function syncVersions() {
      if (!agentId) {
        setVersions([]);
        setVersionsNote(null);
        return;
      }
      setIsLoadingVersions(true);
      setVersionsNote(null);
      try {
        const nextState = await loadPromptVersions(agentId);
        if (!cancelled) {
          setVersions(nextState.versions);
          setVersionsNote(nextState.versionsNote);
        }
      } catch (cause) {
        if (!cancelled) {
          setVersions([]);
          setVersionsNote(cause instanceof Error ? cause.message : "无法加载 Prompt 版本");
        }
      } finally {
        if (!cancelled) {
          setIsLoadingVersions(false);
        }
      }
    }

    void syncVersions();

    return () => {
      cancelled = true;
    };
  }, [agentId]);

  async function reloadVersions() {
    if (!agentId) {
      setVersions([]);
      setVersionsNote(null);
      return;
    }
    const nextState = await loadPromptVersions(agentId);
    setVersions(nextState.versions);
    setVersionsNote(nextState.versionsNote);
  }

  return {
    versions,
    versionsNote,
    isLoadingVersions,
    reloadVersions,
  };
}

export function useAgentPromptFeedbackHistory(agentId: string | null): AgentPromptFeedbackHistoryState {
  const [feedbackHistory, setFeedbackHistory] = useState<PromptFeedbackItem[]>([]);
  const [isFeedbackHistoryLoading, setIsFeedbackHistoryLoading] = useState(false);
  const [feedbackHistoryError, setFeedbackHistoryError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function syncFeedbackHistory() {
      if (!agentId) {
        setFeedbackHistory([]);
        setFeedbackHistoryError(null);
        return;
      }
      setIsFeedbackHistoryLoading(true);
      setFeedbackHistoryError(null);
      try {
        const feedback = await loadPromptFeedbackHistory(agentId);
        if (!cancelled) {
          setFeedbackHistory(feedback);
        }
      } catch (cause) {
        if (!cancelled) {
          setFeedbackHistory([]);
          setFeedbackHistoryError(cause instanceof Error ? cause.message : "无法加载 Prompt Feedback 历史");
        }
      } finally {
        if (!cancelled) {
          setIsFeedbackHistoryLoading(false);
        }
      }
    }

    void syncFeedbackHistory();

    return () => {
      cancelled = true;
    };
  }, [agentId]);

  async function reloadFeedbackHistory() {
    if (!agentId) {
      setFeedbackHistory([]);
      setFeedbackHistoryError(null);
      return;
    }
    const feedback = await loadPromptFeedbackHistory(agentId);
    setFeedbackHistory(feedback);
    setFeedbackHistoryError(null);
  }

  return {
    feedbackHistory,
    isFeedbackHistoryLoading,
    feedbackHistoryError,
    reloadFeedbackHistory,
  };
}
