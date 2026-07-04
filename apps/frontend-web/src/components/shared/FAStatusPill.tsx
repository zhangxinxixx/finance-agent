import type { ReactNode } from "react";
import { getStatusMeta, type FAStatusTone, type StatusDomain, type StatusLike } from "./statusMeta";

export type { FAStatusTone } from "./statusMeta";

interface FAStatusPillProps {
  tone?: FAStatusTone;
  status?: StatusLike;
  domain?: StatusDomain;
  label?: string;
  children: ReactNode;
  dot?: boolean;
  className?: string;
  title?: string;
}

const toneStyles: Record<FAStatusTone, string> = {
  up: "border-[var(--up-border)] bg-[var(--up-soft)] text-[var(--up)]",
  down: "border-[var(--down-border)] bg-[var(--down-soft)] text-[var(--down)]",
  warn: "border-[var(--warn-border)] bg-[var(--warn-soft)] text-[var(--warn)]",
  info: "border-[var(--info-border)] bg-[var(--info-soft)] text-[var(--info)]",
  dim: "border-[var(--border-faint)] bg-[var(--bg-panel)] text-[var(--fg-4)]",
  neutral: "border-[var(--border)] bg-[var(--bg-card-inner)] text-[var(--fg-3)]",
};

export function FAStatusPill({ tone, status, domain, label, children, dot = true, className = "", title }: FAStatusPillProps) {
  const meta = status !== undefined ? getStatusMeta(status, { domain, label }) : null;
  const resolvedTone = tone ?? meta?.tone ?? "neutral";
  const resolvedTitle = title ?? (meta?.explicit ? meta.label : undefined);

  return (
    <span
      title={resolvedTitle}
      className={`inline-flex items-center gap-1 rounded-[var(--radius-pill)] border px-2 py-0.5 text-[11px] font-semibold leading-[1.35] tracking-[0] ${toneStyles[resolvedTone]} ${className}`}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      <span>{children ?? meta?.label}</span>
    </span>
  );
}
