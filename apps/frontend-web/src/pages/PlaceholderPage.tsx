import { FACard } from "@/components/shared/FACard";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { FAStatusPill } from "@/components/shared/FAStatusPill";

interface PlaceholderPageProps {
  title: string;
  description?: string;
}

/**
 * PlaceholderPage — 非 P0 页面的导航占位
 */
export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <div className="finance-page-shell">
      <FACard
        title={title}
        eyebrow="Workstation Placeholder"
        accent="info"
        action={<FAStatusPill tone="dim">planned</FAStatusPill>}
        bodyClassName="space-y-4"
      >
        <FASectionHeader
          title={title}
          description={description || `${title} 页面将在后续阶段实现。`}
        />
        <div className="max-w-2xl rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2.5 text-[11px] leading-5 text-finance-text-muted">
          该页面已注册为导航占位页，当前仅继承 `FinAnalytics_Preview.html` 的全局视觉壳层，不补造业务数据。
        </div>
      </FACard>
    </div>
  );
}
