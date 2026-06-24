import type { CSSProperties } from "react";

export const SECTION_STYLE: CSSProperties = {
  padding: "10px 12px",
  borderBottom: "1px solid var(--border-faint)",
};

export const FINAL_SECTION_STYLE: CSSProperties = {
  padding: "10px 12px",
};

export const CALENDAR_GRID_TEMPLATE = "40px 1fr 52px 52px";

export const CALENDAR_HEADER_STYLE: CSSProperties = {
  display: "grid",
  gridTemplateColumns: CALENDAR_GRID_TEMPLATE,
  fontFamily: "var(--font-sans)",
  fontWeight: 500,
  fontSize: 8,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--fg-5)",
  marginBottom: 4,
};

export const CALENDAR_ROW_STYLE: CSSProperties = {
  display: "grid",
  gridTemplateColumns: CALENDAR_GRID_TEMPLATE,
  padding: "5px 0",
  borderBottom: "1px solid var(--border-faint)",
  alignItems: "center",
};

export const SECTION_LIST_STYLE: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 5,
};

export const SUBSECTION_TITLE_STYLE: CSSProperties = {
  fontFamily: "var(--font-sans)",
  fontWeight: 600,
  fontSize: 10,
  color: "var(--fg-2)",
};

export const REPORTS_KNOWLEDGE_GRID_STYLE: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: 10,
};

export const TAG_LIST_STYLE: CSSProperties = {
  gap: 4,
};

export function getCalendarImpactColor(impact: string) {
  if (impact === "高") return "#f05252";
  if (impact === "中") return "#f59e0b";
  return "var(--fg-5)";
}

export function getCalendarChangeColor(change: string) {
  if (change.startsWith("+")) return "#10b981";
  if (change.startsWith("-")) return "#f05252";
  return "var(--fg-5)";
}
