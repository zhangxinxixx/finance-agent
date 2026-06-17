import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { KnowledgeDetailTab, KnowledgeOpsTab, KnowledgeTypeTab } from "@/types/knowledge";

interface UseKnowledgeSelectionSyncOptions {
  dataSelectedId?: string | null;
  selectedId: string | null;
  setSelectedId: (selectedId: string | null) => void;
}

export function useKnowledgeSelectionSync({
  dataSelectedId,
  selectedId,
  setSelectedId,
}: UseKnowledgeSelectionSyncOptions) {
  useEffect(() => {
    if (dataSelectedId && !selectedId) {
      setSelectedId(dataSelectedId);
    }
  }, [dataSelectedId, selectedId, setSelectedId]);
}

export function useKnowledgePageState() {
  const navigate = useNavigate();
  const { knowledgeId } = useParams();
  const [search, setSearch] = useState("");
  const [topic, setTopic] = useState("全部主题");
  const [status, setStatus] = useState("全部状态");
  const [typeTab, setTypeTab] = useState<KnowledgeTypeTab>("all");
  const [selectedId, setSelectedId] = useState<string | null>(knowledgeId ?? null);
  const [detailTab, setDetailTab] = useState<KnowledgeDetailTab>("overview");
  const [opsTab, setOpsTab] = useState<KnowledgeOpsTab>("pinned");

  useEffect(() => {
    if (knowledgeId && knowledgeId !== selectedId) {
      setSelectedId(knowledgeId);
      setDetailTab("overview");
    }
  }, [knowledgeId, selectedId]);

  const handleSelectItem = useCallback(
    (id: string) => {
      setSelectedId(id);
      setDetailTab("overview");
      navigate(`/knowledge/${id}`);
    },
    [navigate],
  );

  const resetSelectionToList = useCallback(() => {
    setSelectedId(null);
    if (knowledgeId) navigate("/knowledge-base");
  }, [knowledgeId, navigate]);

  const handleTopicFilter = useCallback(
    (nextTopic: string) => {
      setTopic(nextTopic);
      resetSelectionToList();
    },
    [resetSelectionToList],
  );

  const handleStatusFilter = useCallback(
    (nextStatus: string) => {
      setStatus(nextStatus);
      resetSelectionToList();
    },
    [resetSelectionToList],
  );

  const handleTypeTabChange = useCallback(
    (next: KnowledgeTypeTab) => {
      setTypeTab(next);
      resetSelectionToList();
    },
    [resetSelectionToList],
  );

  return {
    knowledgeId,
    search,
    setSearch,
    topic,
    status,
    typeTab,
    selectedId,
    setSelectedId,
    detailTab,
    setDetailTab,
    opsTab,
    setOpsTab,
    handleSelectItem,
    handleTopicFilter,
    handleStatusFilter,
    handleTypeTabChange,
  };
}
