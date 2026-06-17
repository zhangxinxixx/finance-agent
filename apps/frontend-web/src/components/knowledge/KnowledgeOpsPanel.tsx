import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { KnowledgeItem, KnowledgeOpsTab, KnowledgeViewModel } from "@/types/knowledge";

interface KnowledgeOpsPanelProps {
  stats: KnowledgeViewModel["stats"];
  selectedItem: KnowledgeItem | null;
  allItems: KnowledgeItem[];
  activeTab: KnowledgeOpsTab;
  onTabChange: (tab: KnowledgeOpsTab) => void;
}

const OPS_TABS: Array<{ id: KnowledgeOpsTab; label: string }> = [
  { id: "pinned", label: "置顶资产" },
  { id: "agent", label: "智能体资产" },
  { id: "distill", label: "沉淀工厂" },
  { id: "recent", label: "高引用" },
  { id: "recommend", label: "补强建议" },
];

const TYPE_ICON_CLASS: Record<string, string> = {
  method: "bg-[var(--info-soft)] text-[var(--info)]",
  playbook: "bg-[rgba(139,92,246,0.12)] text-[var(--chart-5)]",
  note: "bg-[var(--up-soft)] text-[var(--up)]",
  review: "bg-[var(--warn-soft)] text-[var(--warn)]",
  agent: "bg-[rgba(229,163,46,0.12)] text-[var(--chart-1)]",
  dict: "bg-[var(--down-soft)] text-[var(--down)]",
};

const TYPE_GLYPH: Record<string, string> = {
  method: "法",
  playbook: "▣",
  note: "记",
  review: "复",
  agent: "A",
  dict: "字",
};

export function KnowledgeOpsPanel({ stats, selectedItem, allItems, activeTab, onTabChange }: KnowledgeOpsPanelProps) {
  const reviewItems = allItems.filter((item) => item.reviewQueued);
  const pinnedItems = allItems.filter((item) => item.pinned);
  const agentItems = allItems.filter((item) => item.agentReady).slice(0, 4);
  const recentItems = [...allItems].sort((a, b) => b.citations - a.citations).slice(0, 4);
  const recommendItems = allItems
    .filter((item) => item.id !== selectedItem?.id)
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 3);

  return (
    <div className="flex min-h-0 flex-col gap-3">
      {/* Stats Overview */}
      <FACard title="知识库概览" eyebrow="统计" accent="brand" bodyClassName="space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <FAMetricCard label="总资产" value={stats.total} hint="精选研究资产" />
          <FAMetricCard label="智能体资产" value={stats.agentReady} hint="Prompt / 搜索双入口" />
          <FAMetricCard label="待复核" value={stats.reviewQueueCount} hint="需要人工二次校验" trend={stats.reviewQueueCount > 0 ? "down" : "flat"} />
          <FAMetricCard label="剧本模板" value={stats.playbookCount} hint={`候选 ${stats.playbookCandidateCount}`} />
        </div>
      </FACard>

      {/* Sync Health */}
      <FACard title="同步健康" eyebrow="Sync" accent="info" bodyClassName="space-y-2">
        <SyncItem name="Obsidian" status="已同步" color="green" />
        <SyncItem name="Mem0 / 向量库" status="已索引" color="green" />
        <SyncItem name="回测样本库" status="待补样本" color="orange" />
        {selectedItem && (
          <p className="mt-1 text-[10px] text-[var(--fg-5)]">
            当前焦点：{selectedItem.title}
          </p>
        )}
      </FACard>

      {/* Review Queue */}
      {reviewItems.length > 0 && (
        <FACard title="复核 / 过期队列" eyebrow="Review" accent="warn" bodyClassName="space-y-2">
          {reviewItems.map((item) => (
            <div key={item.id} className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{item.title}</span>
                <span className="fa-num shrink-0 text-[10px] text-[var(--fg-5)]">{item.verifiedAt}</span>
              </div>
              <FAStatusPill tone="warn" className="mt-1.5">{item.status}</FAStatusPill>
            </div>
          ))}
        </FACard>
      )}

      {/* Tabbed Content */}
      <FACard title="资产与沉淀" eyebrow="Assets" accent="info" bodyClassName="space-y-3">
        <div className="flex flex-wrap gap-1">
          {OPS_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={`rounded-[var(--radius-pill)] px-2 py-1 text-[10px] font-semibold transition-colors ${
                activeTab === tab.id
                  ? "bg-[var(--bg-active)] text-[var(--brand-hover)]"
                  : "text-[var(--fg-5)] hover:bg-[var(--bg-hover)] hover:text-[var(--fg-3)]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === "pinned" && (
          <div className="space-y-2">
            {pinnedItems.map((item) => (
              <MiniAssetRow key={item.id} item={item} />
            ))}
          </div>
        )}

        {activeTab === "agent" && (
          <div className="space-y-2">
            {agentItems.map((item) => (
              <MiniAssetRow key={item.id} item={item} meta={`输入 ${item.inputs.slice(0, 3).join(" / ")}`} />
            ))}
          </div>
        )}

        {activeTab === "distill" && (
          <div className="space-y-2">
            <DistillButton title="从研究报告沉淀" subtitle="长文报告 -> 研究笔记 / 方法论骨架" />
            <DistillButton title="升级为剧本模板" subtitle="把成功动作和失败禁令变成盘中执行模板" />
            <DistillButton title="补验证样本" subtitle="为阶段知识补异质场景，决定是否升级长期有效" />
          </div>
        )}

        {activeTab === "recent" && (
          <div className="space-y-2">
            {recentItems.map((item) => (
              <div key={item.id} className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{item.title}</span>
                  <span className="fa-num shrink-0 text-[10px] text-[var(--fg-5)]">引用 {item.citations}</span>
                </div>
                <p className="mt-1 truncate text-[10px] text-[var(--fg-4)]">{item.summary}</p>
              </div>
            ))}
          </div>
        )}

        {activeTab === "recommend" && (
          <div className="space-y-2">
            {recommendItems.map((item, index) => (
              <div key={item.id} className="flex gap-2.5 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-2.5">
                <span className={`flex h-[28px] w-[28px] shrink-0 items-center justify-center rounded-[var(--radius-md)] text-[11px] font-bold ${TYPE_ICON_CLASS[item.type]}`}>
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{item.title}</div>
                  <div className="mt-1 text-[10px] text-[var(--fg-5)]">{item.typeLabel} / 可信度 {item.confidence}% / {item.status}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </FACard>
    </div>
  );
}

function SyncItem({ name, status, color }: { name: string; status: string; color: "green" | "orange" | "red" }) {
  const dotClass = color === "green" ? "bg-[var(--up)]" : color === "orange" ? "bg-[var(--warn)]" : "bg-[var(--down)]";
  return (
    <div className="flex items-center gap-2.5 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2.5">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dotClass}`} />
      <span className="text-[11px] font-semibold text-[var(--fg-2)]">{name}</span>
      <span className="ml-auto text-[10px] text-[var(--fg-4)]">{status}</span>
    </div>
  );
}

function MiniAssetRow({ item, meta }: { item: KnowledgeItem; meta?: string }) {
  return (
    <div className="flex items-center gap-2.5 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2.5">
      <span
        className={`flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-[var(--radius-sm)] text-[10px] font-bold ${TYPE_ICON_CLASS[item.type] ?? TYPE_ICON_CLASS.method}`}
      >
        {TYPE_GLYPH[item.type] ?? "?"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{item.title}</div>
        <div className="mt-0.5 text-[10px] text-[var(--fg-5)]">
          {meta ?? `${item.version} / 验证 ${item.verifiedAt} / 引用 ${item.citations}`}
        </div>
      </div>
    </div>
  );
}

function DistillButton({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <button
      type="button"
      className="w-full rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3 text-left transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
    >
      <div className="text-[11px] font-semibold text-[var(--fg-2)]">{title}</div>
      <div className="mt-1 text-[10px] text-[var(--fg-4)]">{subtitle}</div>
    </button>
  );
}
