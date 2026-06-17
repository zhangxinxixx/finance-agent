import type { ReactNode } from "react";
import { Inbox } from "lucide-react";
import { FAIcon } from "./FAIcon";

interface FAEmptyStateProps {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function FAEmptyState({ title = "暂无数据", description = "当前视图没有可展示的数据。", action, className = "" }: FAEmptyStateProps) {
  return (
    <div
      role="status"
      className={`flex flex-col items-center justify-center rounded-[var(--radius-lg)] border border-dashed border-[var(--border)] bg-[var(--bg-card)] px-5 py-7 text-center ${className}`}
    >
      <FAIcon icon={Inbox} tone="dim" />
      <div className="mt-3 text-[13px] font-semibold text-[var(--fg-2)]">{title}</div>
      <div className="mt-1 max-w-md text-[11px] leading-relaxed text-[var(--fg-4)]">{description}</div>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
