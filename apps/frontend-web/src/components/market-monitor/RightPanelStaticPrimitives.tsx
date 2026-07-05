import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import {
  CALENDAR_HEADER_STYLE,
  CALENDAR_ROW_STYLE,
  SUBSECTION_TITLE_STYLE,
  getCalendarChangeColor,
  getCalendarImpactColor,
} from "./rightPanelStaticSectionStyles";

export function StaticSubsectionTitle({
  icon: Icon,
  title,
}: {
  icon: LucideIcon;
  title: string;
}) {
  return (
    <div className="flex items-center gap-1.5" style={{ marginBottom: 6 }}>
      <Icon size={11} style={{ color: "var(--fg-5)" }} />
      <span style={SUBSECTION_TITLE_STYLE}>{title}</span>
    </div>
  );
}

export function CalendarColumnHeader() {
  return (
    <div style={CALENDAR_HEADER_STYLE}>
      <span>日期</span>
      <span>事件</span>
      <span style={{ textAlign: "center" }}>影响</span>
      <span style={{ textAlign: "right" }}>周变动</span>
    </div>
  );
}

export function CalendarDataRow({
  time,
  event,
  impact,
  change,
}: {
  time: string;
  event: string;
  impact: string;
  change: string;
}) {
  return (
    <div style={CALENDAR_ROW_STYLE}>
      <span className="fa-num" style={{ fontSize: 9.5, color: "var(--fg-5)" }}>
        {time}
      </span>
      <span style={{ fontFamily: "var(--font-sans)", fontSize: 10, color: "var(--fg-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{event}</span>
      <span
        style={{
          textAlign: "center",
          fontFamily: "var(--font-sans)",
          fontWeight: 500,
          fontSize: 9,
          color: getCalendarImpactColor(impact),
        }}
      >
        {impact}
      </span>
      <span
        className="fa-num"
        style={{
          textAlign: "right",
          fontSize: 9.5,
          fontWeight: 600,
          color: getCalendarChangeColor(change),
        }}
      >
        {change}
      </span>
    </div>
  );
}

export function StaticInfoCard({
  accentColor,
  header,
  badges,
  children,
}: {
  accentColor: string;
  header: ReactNode;
  badges?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        padding: "7px 8px",
        background: "var(--bg-card-inner)",
        border: "1px solid var(--border-faint)",
        borderRadius: 3,
        borderLeft: `2px solid ${accentColor}`,
      }}
    >
      <div className="flex items-center justify-between" style={{ marginBottom: 3 }}>
        {header}
        {badges}
      </div>
      <div style={{ fontFamily: "var(--font-sans)", fontSize: 10.5, lineHeight: 1.45, color: "var(--fg-3)" }}>{children}</div>
    </div>
  );
}

export function StaticCompactRow({
  title,
  meta,
}: {
  title: string;
  meta: string;
}) {
  return (
    <div
      className="flex items-center justify-between"
      style={{
        padding: "5px 6px",
        borderRadius: 3,
        background: "var(--bg-card)",
        border: "1px solid var(--border-faint)",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 9,
          color: "var(--fg-3)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {title}
      </span>
      <span className="fa-num" style={{ fontSize: 8.5, color: "var(--fg-6)", flexShrink: 0, marginLeft: 4 }}>
        {meta}
      </span>
    </div>
  );
}

export function StaticTag({ children }: { children: ReactNode }) {
  return (
    <span
      style={{
        fontFamily: "var(--font-sans)",
        fontSize: 8.5,
        padding: "2px 6px",
        borderRadius: 3,
        border: "1px solid color-mix(in srgb, var(--brand-hover) 18%, var(--border-faint))",
        color: "var(--fg-4)",
        background: "color-mix(in srgb, var(--brand-hover) 4%, var(--bg-card))",
      }}
    >
      {children}
    </span>
  );
}
