import type { CSSProperties, ReactNode } from "react";

const EYEBROW_STYLE: CSSProperties = {
  fontSize: 8,
  fontWeight: 600,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--fg-5)",
  marginBottom: 4,
};

const FILTER_SECTION_STYLE: CSSProperties = {
  marginBottom: 0,
  paddingBottom: 6,
  borderBottom: "1px solid var(--border-faint)",
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
      <div
        style={{
        display: "flex",
        flexDirection: "column",
        gap: 1,
        padding: "3px",
        borderRadius: 5,
        background: "rgba(255,255,255,0.018)",
        border: "1px solid var(--border-faint)",
      }}
      >
        {children}
      </div>
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
        minHeight: 24,
        padding: "3px 7px",
        borderRadius: 4,
        background: isActive ? "color-mix(in srgb, var(--brand-soft) 78%, transparent)" : "transparent",
        border: isActive ? "1px solid var(--brand-border)" : "1px solid transparent",
        color: isActive ? "var(--brand-hover)" : "var(--fg-3)",
        fontSize: 9,
        fontWeight: isActive ? 600 : 400,
        cursor: "pointer",
        marginBottom: 0,
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
        minHeight: 24,
        padding: "3px 6px",
        borderRadius: 4,
        cursor: "pointer",
        marginBottom: 0,
        background: isActive ? "color-mix(in srgb, var(--brand-soft) 78%, transparent)" : "transparent",
        transition: "background 120ms, border-color 120ms",
        border: `1px solid ${isActive ? "var(--brand-border)" : "transparent"}`,
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
      <span style={{ fontSize: 9, color: isActive ? "var(--fg-2)" : "var(--fg-3)", flex: 1, fontWeight: isActive ? 600 : 500 }}>{label}</span>
      {typeof count === "number" ? (
        <span style={{ fontSize: 8, color: isActive ? "var(--brand-hover)" : "var(--fg-5)", fontFamily: "var(--font-mono)" }}>
          {count}
        </span>
      ) : null}
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
        minHeight: 24,
        padding: "3px 6px",
        borderRadius: 4,
        cursor: "pointer",
        marginBottom: 0,
        background: isActive ? "color-mix(in srgb, var(--brand-soft) 78%, transparent)" : "transparent",
        border: `1px solid ${isActive ? "var(--brand-border)" : "transparent"}`,
        textAlign: "left",
      }}
    >
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, flexShrink: 0 }} />
      <span
        style={{
          fontSize: 9,
          color: isActive ? "var(--brand-hover)" : "var(--fg-2)",
          flex: 1,
          fontWeight: isActive ? 600 : 500,
        }}
      >
        {label}
      </span>
    </button>
  );
}

export function ReportsRailDateRangeGrid({ children }: { children: ReactNode }) {
  return <div style={{ ...DATE_RANGE_GRID_STYLE, gap: 3 }}>{children}</div>;
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
        minHeight: 24,
        padding: "4px 6px",
        borderRadius: 4,
        fontSize: 9,
        textAlign: "center",
        cursor: "pointer",
        background: isActive ? "color-mix(in srgb, var(--brand-soft) 78%, transparent)" : "var(--bg-card-inner)",
        color: isActive ? "var(--brand-hover)" : "var(--fg-3)",
        border: isActive ? "1px solid var(--brand-border)" : "1px solid var(--border)",
        fontWeight: isActive ? 600 : 500,
      }}
    >
      {label}
    </button>
  );
}
