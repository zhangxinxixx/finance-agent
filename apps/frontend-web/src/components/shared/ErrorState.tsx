import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  retryLabel?: string;
  children?: ReactNode;
  className?: string;
}

export function ErrorState({
  title = "加载失败",
  message = "数据请求或解析失败，请稍后重试。",
  onRetry,
  retryLabel = "重新加载",
  children,
  className = "",
}: ErrorStateProps) {
  return (
    <div className={`finance-panel flex flex-col items-center justify-center gap-2 border-[var(--down-border)] bg-[var(--down-soft)] p-6 text-center ${className}`}>
      <AlertTriangle size={20} className="text-finance-bearish" />
      <div className="text-sm font-semibold text-finance-text-primary">{title}</div>
      <div className="max-w-md text-xs leading-relaxed text-finance-text-secondary">{message}</div>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-md border border-finance-border px-3 py-1.5 text-xs font-semibold text-finance-text-primary transition-colors hover:border-finance-accent hover:text-finance-accent-soft"
        >
          {retryLabel}
        </button>
      ) : null}
      {children ? <div className="mt-2">{children}</div> : null}
    </div>
  );
}
