import { useEffect, useMemo, useState } from "react";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { PlaybookTemplateDetail } from "@/components/playbook/PlaybookTemplateDetail";
import { PlaybookTemplateList } from "@/components/playbook/PlaybookTemplateList";
import { usePlaybooks } from "@/hooks/usePlaybooks";

export function PlaybookRegistrySection() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const playbooks = usePlaybooks(selectedId);

  useEffect(() => {
    if (playbooks.data?.selectedId && !selectedId) {
      setSelectedId(playbooks.data.selectedId);
    }
  }, [playbooks.data?.selectedId, selectedId]);

  const selectedItem = useMemo(() => playbooks.data?.selectedItem ?? null, [playbooks.data?.selectedItem]);

  if (playbooks.isLoading && !playbooks.data) {
    return <LoadingSkeleton variant="panel" />;
  }

  if (playbooks.isError || !playbooks.data) {
    return (
      <div className="space-y-3">
        <FASectionHeader title="剧本模板库" eyebrow="模板登记" description="模板登记与版本历史" />
        <FAEmptyState
          title="剧本模板视图不可用"
          description={playbooks.error?.message ?? "当前无法读取剧本模板登记信息。"}
          action={
            <button
              type="button"
              onClick={playbooks.refetch}
              className="rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-2)]"
            >
              重试
            </button>
          }
        />
      </div>
    );
  }

  return (
    <section className="space-y-3">
      <FASectionHeader
        title="剧本模板库"
        eyebrow="模板登记"
        description="只读浏览模板登记、版本历史和来源引用，不在前端做匹配计算。"
      />
      <div className="grid gap-3 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="min-h-0">
          <PlaybookTemplateList items={playbooks.data.items} selectedId={selectedId ?? playbooks.data.selectedId} onSelect={setSelectedId} />
        </div>
        <div className="min-h-0">
          <PlaybookTemplateDetail item={selectedItem} />
        </div>
      </div>
    </section>
  );
}
