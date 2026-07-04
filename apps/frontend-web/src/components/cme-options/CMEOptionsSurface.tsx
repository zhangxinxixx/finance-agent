import type { CSSProperties, ReactNode } from "react";

interface CMEOptionsSurfaceProps {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  bodyStyle?: CSSProperties;
}

export function CMEOptionsSurface({ title, action, children, bodyStyle }: CMEOptionsSurfaceProps) {
  return (
    <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", overflow: "hidden" }}>
      {(title || action) && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", background: "var(--bg-panel)", borderBottom: "1px solid var(--border)" }}>
          {title ? <span className="cme-options-surface-title">{title}</span> : null}
          {action}
        </div>
      )}
      <div style={{ padding: 12, ...bodyStyle }}>{children}</div>
    </div>
  );
}
