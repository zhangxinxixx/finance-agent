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
  const statRows = [
    { label: "总资产", value: stats.total || allItems.length, meta: "精选研究资产" },
    { label: "智能体资产", value: stats.agentReady || allItems.filter((item) => item.agentReady).length, meta: "Prompt / 搜索双入口" },
    { label: "待复核", value: stats.reviewQueueCount || reviewItems.length, meta: "需要人工二次校验" },
    { label: "剧本模板", value: stats.playbookCount || allItems.filter((item) => item.type === "playbook").length, meta: `候选 ${stats.playbookCandidateCount || allItems.filter((item) => item.playbookReady).length}` },
  ];

  return (
    <aside className="knowledge-ops-panel">
      <section className="knowledge-ops-section">
        <SectionHeading eyebrow="统计" title="知识库概览" />
        <div className="knowledge-stat-list">
          {statRows.map((row) => (
            <div key={row.label} className="knowledge-stat-row">
              <span>{row.label}</span>
              <strong className="fa-num">{row.value}</strong>
              <em>{row.meta}</em>
            </div>
          ))}
        </div>
      </section>

      <section className="knowledge-ops-section">
        <SectionHeading eyebrow="Sync" title="同步健康" />
        <div className="knowledge-row-list">
          <SyncItem name="本地知识库" status="已同步" color="green" />
          <SyncItem name="回测样本库" status="待补样本" color="orange" />
        </div>
        {selectedItem && (
          <p className="knowledge-reader-note">
            当前焦点：{selectedItem.title}
          </p>
        )}
      </section>

      {reviewItems.length > 0 && (
        <section className="knowledge-ops-section">
          <SectionHeading eyebrow="复核" title="复核 / 过期队列" />
          <div className="knowledge-row-list">
            {reviewItems.map((item) => (
              <div key={item.id} className="knowledge-row-item knowledge-row-item--stacked">
                <div className="knowledge-row-meta">
                  <span>{item.title}</span>
                  <span className="fa-num">{item.verifiedAt}</span>
                </div>
                <FAStatusPill tone="warn" className="mt-1.5">{item.status}</FAStatusPill>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="knowledge-ops-section">
        <SectionHeading eyebrow="Assets" title="资产与沉淀" />
        <div className="knowledge-ops-tabs">
          {OPS_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={activeTab === tab.id ? "is-active" : ""}
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
          <div className="knowledge-row-list">
            {recentItems.map((item) => (
              <div key={item.id} className="knowledge-row-item knowledge-row-item--stacked">
                <div className="knowledge-row-meta">
                  <span>{item.title}</span>
                  <span className="fa-num">引用 {item.citations}</span>
                </div>
                <p className="knowledge-row-copy">{item.summary}</p>
              </div>
            ))}
          </div>
        )}

        {activeTab === "recommend" && (
          <div className="knowledge-row-list">
            {recommendItems.map((item, index) => (
              <div key={item.id} className="knowledge-row-item">
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
      </section>
    </aside>
  );
}

function SectionHeading({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <header className="knowledge-ops-heading">
      <span>{eyebrow}</span>
      <strong>{title}</strong>
    </header>
  );
}

function SyncItem({ name, status, color }: { name: string; status: string; color: "green" | "orange" | "red" }) {
  const dotClass = color === "green" ? "bg-[var(--up)]" : color === "orange" ? "bg-[var(--warn)]" : "bg-[var(--down)]";
  return (
    <div className="knowledge-row-item">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dotClass}`} />
      <span className="text-[11px] font-semibold text-[var(--fg-2)]">{name}</span>
      <span className="ml-auto text-[10px] text-[var(--fg-4)]">{status}</span>
    </div>
  );
}

function MiniAssetRow({ item, meta }: { item: KnowledgeItem; meta?: string }) {
  return (
    <div className="knowledge-row-item">
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
      className="knowledge-distill-button"
    >
      <div className="text-[11px] font-semibold text-[var(--fg-2)]">{title}</div>
      <div className="mt-1 text-[10px] text-[var(--fg-4)]">{subtitle}</div>
    </button>
  );
}
