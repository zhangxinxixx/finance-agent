import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  title?: string;
  description?: string;
  children?: ReactNode;
  className?: string;
}

export function EmptyState({ title = "暂无数据", description = "当前选择下没有可展示的数据。", children, className = "" }: EmptyStateProps) {
  return (
    <div className={`finance-panel flex flex-col items-center justify-center gap-2 border-dashed p-6 text-center ${className}`}>
      <Inbox size={20} className="text-finance-text-muted" />
      <div className="text-sm font-semibold text-finance-text-primary">{title}</div>
      <div className="max-w-md text-xs leading-relaxed text-finance-text-secondary">{description}</div>
      {children ? <div className="mt-2">{children}</div> : null}
    </div>
  );
}
