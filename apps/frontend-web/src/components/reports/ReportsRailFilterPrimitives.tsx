import type { CSSProperties, ReactNode } from "react";

const EYEBROW_STYLE: CSSProperties = {
  fontSize: 9,
  fontWeight: 600,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--fg-5)",
  marginBottom: 6,
};

const FILTER_SECTION_STYLE: CSSProperties = {
  marginBottom: 14,
};

const DATE_RANGE_GRID_STYLE: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 4,
};

export function ReportsRailEyebrowHeader({ label }: { label: string }) {
  return <div style={EYEBROW_STYLE}>{label}</div>;
}

export function ReportsRailFilterSection({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div style={FILTER_SECTION_STYLE}>
      <ReportsRailEyebrowHeader label={label} />
      {children}
    </div>
  );
}

export function ReportsRailTextOptionButton({
  isActive,
  onClick,
  children,
}: {
  isActive: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "4px 8px",
        borderRadius: 3,
        background: isActive ? "var(--brand-dim)" : "transparent",
        border: isActive ? "1px solid var(--brand)" : "1px solid transparent",
        color: isActive ? "var(--brand-hover)" : "var(--fg-3)",
        fontSize: 10,
        fontWeight: isActive ? 600 : 400,
        cursor: "pointer",
        marginBottom: 1,
      }}
    >
      {children}
    </button>
  );
}

export function ReportsRailColorOptionButton({
  isActive,
  color,
  label,
  count,
  onClick,
}: {
  isActive: boolean;
  color: string;
  label: string;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={isActive}
      onClick={onClick}
      style={{
        display: "flex",
        width: "100%",
        alignItems: "center",
        gap: 6,
        padding: "3px 6px",
        borderRadius: 3,
        cursor: "pointer",
        marginBottom: 1,
        background: isActive ? "var(--brand-dim)" : "transparent",
        transition: "background 120ms",
        border: "none",
        textAlign: "left",
      }}
    >
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: 2,
          background: isActive ? color : `${color}33`,
          border: `1px solid ${color}66`,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {isActive ? <span style={{ width: 6, height: 6, borderRadius: 1, background: "#fff" }} /> : null}
      </span>
      <span style={{ fontSize: 10, color: isActive ? "var(--fg-2)" : "var(--fg-3)", flex: 1 }}>{label}</span>
      {typeof count === "number" ? <span style={{ fontSize: 9, color: "var(--fg-5)" }}>{count}</span> : null}
    </button>
  );
}

export function ReportsRailDotOptionButton({
  isActive,
  color,
  label,
  onClick,
}: {
  isActive: boolean;
  color: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={isActive}
      onClick={onClick}
      style={{
        display: "flex",
        width: "100%",
        alignItems: "center",
        gap: 6,
        padding: "3px 8px",
        borderRadius: 3,
        cursor: "pointer",
        marginBottom: 1,
        background: isActive ? "var(--brand-dim)" : "transparent",
        border: "none",
        textAlign: "left",
      }}
    >
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, flexShrink: 0 }} />
      <span
        style={{
          fontSize: 10,
          color: isActive ? "var(--brand-hover)" : "var(--fg-2)",
          flex: 1,
          fontWeight: isActive ? 600 : 400,
        }}
      >
        {label}
      </span>
    </button>
  );
}

export function ReportsRailDateRangeGrid({ children }: { children: ReactNode }) {
  return <div style={DATE_RANGE_GRID_STYLE}>{children}</div>;
}

export function ReportsRailDateRangeButton({
  isActive,
  label,
  onClick,
}: {
  isActive: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: "5px 6px",
        borderRadius: 3,
        fontSize: 10,
        textAlign: "center",
        cursor: "pointer",
        background: isActive ? "var(--brand-dim)" : "var(--bg-card-inner)",
        color: isActive ? "var(--brand-hover)" : "var(--fg-3)",
        border: isActive ? "1px solid var(--brand)" : "1px solid var(--border)",
        fontWeight: isActive ? 600 : 500,
      }}
    >
      {label}
    </button>
  );
}
