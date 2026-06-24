import type { ReactNode } from "react";
import { AlertTriangle, Info } from "lucide-react";

interface FAWarningBannerProps {
  title: ReactNode;
  description?: ReactNode;
  tone?: "warn" | "down" | "info";
  action?: ReactNode;
  className?: string;
}

const toneClass: Record<NonNullable<FAWarningBannerProps["tone"]>, { box: string; icon: string }> = {
  warn: { box: "border-[var(--warn-border)] bg-[var(--warn-soft)]", icon: "text-[var(--warn)]" },
  down: { box: "border-[var(--down-border)] bg-[var(--down-soft)]", icon: "text-[var(--down)]" },
  info: { box: "border-[var(--info-border)] bg-[var(--info-soft)]", icon: "text-[var(--info)]" },
};

export function FAWarningBanner({ title, description, tone = "warn", action, className = "" }: FAWarningBannerProps) {
  const Icon = tone === "info" ? Info : AlertTriangle;
  const styles = toneClass[tone];

  return (
    <div className={`flex items-start gap-3 rounded-[var(--radius-lg)] border px-3 py-2.5 ${styles.box} ${className}`}>
      <Icon size={14} className={`mt-0.5 shrink-0 ${styles.icon}`} />
      <div className="min-w-0 flex-1">
        <div className="text-[12px] font-semibold text-[var(--fg-2)]">{title}</div>
        {description ? <div className="mt-0.5 text-[11px] leading-snug text-[var(--fg-4)]">{description}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
