import type { ComponentType, ReactNode } from "react";

interface FAIconProps {
  icon?: ComponentType<{ size?: number | string; className?: string }>;
  children?: ReactNode;
  tone?: "brand" | "info" | "up" | "down" | "warn" | "dim";
  size?: "sm" | "md";
  className?: string;
}

const toneClass: Record<NonNullable<FAIconProps["tone"]>, string> = {
  brand: "text-finance-accent-soft",
  info: "text-finance-cyan",
  up: "text-finance-bullish",
  down: "text-finance-bearish",
  warn: "text-finance-warning",
  dim: "text-finance-text-muted",
};

const sizeClass: Record<NonNullable<FAIconProps["size"]>, string> = {
  sm: "h-5 w-5",
  md: "h-6 w-6",
};

export function FAIcon({ icon: Icon, children, tone = "brand", size = "md", className = "" }: FAIconProps) {
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] ${sizeClass[size]} ${toneClass[tone]} ${className}`}
    >
      {Icon ? <Icon size={size === "sm" ? 11 : 13} /> : children}
    </span>
  );
}
