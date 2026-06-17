import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { PlaybookTemplateDetail } from "@/types/playbook";

interface PlaybookTemplateDetailProps {
  item: PlaybookTemplateDetail | null;
}

function toneForStatus(status: string) {
  if (["published", "long_term", "长期有效"].includes(status)) return "up";
  if (["candidate", "draft", "待复核", "阶段有效"].includes(status)) return "warn";
  if (["deprecated", "archived"].includes(status)) return "down";
  return "neutral";
}

export function PlaybookTemplateDetail({ item }: PlaybookTemplateDetailProps) {
  if (!item) {
    return <FAEmptyState title="未选中模板" description="选择左侧剧本模板查看版本历史与规则细节。" />;
  }

  return (
    <div className="space-y-3">
      <FACard
        title={item.title}
        eyebrow="剧本模板"
        accent="brand"
        action={<FAStatusPill tone={toneForStatus(item.status)}>{item.status}</FAStatusPill>}
        bodyClassName="space-y-3"
      >
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <FAMetricCard label="Playbook ID" value={item.playbook_id} />
          <FAMetricCard label="版本" value={item.version} />
          <FAMetricCard label="最近验证" value={item.last_validated ?? "未验证"} />
          <FAMetricCard label="版本数" value={item.versions.length} />
        </div>
        <p className="text-[12px] leading-relaxed text-[var(--fg-3)]">{item.summary}</p>
      </FACard>

      <div className="grid gap-3 lg:grid-cols-2">
        <FACard title="条件与动作" eyebrow="Registry" accent="info" bodyClassName="space-y-3">
          <PlaybookBulletList title="触发条件" items={item.conditions} empty="暂无触发条件" />
          <PlaybookBulletList title="执行动作" items={item.actions} empty="暂无执行动作" />
          <PlaybookBulletList title="失效条件" items={item.invalidations} empty="暂无失效条件" />
        </FACard>

        <FACard title="来源与历史" eyebrow="Trace" accent="warn" bodyClassName="space-y-3">
          <PlaybookBulletList
            title="来源引用"
            items={item.source_refs.map((ref) => ref.label ? `${ref.source_ref} · ${ref.label}` : ref.source_ref)}
            empty="暂无来源引用"
          />
          <div className="space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">版本历史</p>
            {item.versions.length > 0 ? (
              item.versions.map((version) => (
                <div key={`${version.playbook_id}:${version.version}`} className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold text-[var(--fg-2)]">{version.version}</span>
                    <span className="fa-num text-[10px] text-[var(--fg-5)]">{version.created_at ?? "未记录"}</span>
                  </div>
                  <p className="mt-1 text-[10px] text-[var(--fg-4)]">{version.reason ?? "无备注"}</p>
                </div>
              ))
            ) : (
              <FAEmptyState title="暂无版本历史" description="当前模板还没有历史版本。" />
            )}
          </div>
        </FACard>
      </div>
    </div>
  );
}

function PlaybookBulletList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{title}</p>
      {items.length > 0 ? (
        <div className="space-y-1.5">
          {items.map((item) => (
            <div key={item} className="flex gap-2 text-[11px] text-[var(--fg-3)]">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--brand)]" />
              <span className="leading-relaxed">{item}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[11px] text-[var(--fg-4)]">{empty}</p>
      )}
    </div>
  );
}
