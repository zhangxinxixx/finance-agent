import type { ReactNode } from "react";

export function compactPanelText(text: string | null | undefined, maxLength: number): string {
  const value = (text || "").replace(/<[^>]*>/g, "").trim();
  if (!value) return "—";
  return value.length > maxLength ? `${value.slice(0, maxLength).trim()}...` : value;
}

export function calendarPanelValue(value: string | null | undefined): string {
  return value && value.trim() ? value : "—";
}

export function formatPanelTime(value: string | null | undefined): string {
  const time = value ? new Date(value) : null;
  if (!time || Number.isNaN(time.getTime())) {
    return "—";
  }
  return `${String(time.getHours()).padStart(2, "0")}:${String(time.getMinutes()).padStart(2, "0")}`;
}

export function formatPanelDate(value: string | null | undefined): string {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) {
    return "—";
  }
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function DashboardPanelEmptyState({
  children,
  border = "1px solid var(--border-faint)",
  background = "var(--bg-card-inner)",
}: {
  children: ReactNode;
  border?: string;
  background?: string;
}) {
  return (
    <div
      style={{
        padding: "8px",
        borderRadius: 3,
        background,
        border,
        fontSize: 10,
        color: "var(--fg-5)",
        textAlign: "center",
      }}
    >
      {children}
    </div>
  );
}

export function DashboardPanelStack({ children }: { children: ReactNode }) {
  return <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>{children}</div>;
}

export function DashboardPanelCard({
  children,
  background = "var(--bg-card-inner)",
  border = "1px solid var(--border-faint)",
}: {
  children: ReactNode;
  background?: string;
  border?: string;
}) {
  return (
    <div
      style={{
        padding: "6px 8px",
        borderRadius: 3,
        background,
        border,
      }}
    >
      {children}
    </div>
  );
}
