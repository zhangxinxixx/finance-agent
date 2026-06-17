import { BookOpen, Calendar, FileText, Zap } from "lucide-react";
import { ContextPanelSectionHeader } from "@/components/shared/ContextPanel";
import {
  CALENDAR_ITEMS,
  EVENT_IMPACT_COLOR,
  EVENT_IMPACT_LABEL,
  EVENT_ITEMS,
  KNOWLEDGE_TAGS,
  REPORT_ITEMS,
} from "./rightPanelStaticData";
import {
  CalendarColumnHeader,
  CalendarDataRow,
  StaticCompactRow,
  StaticInfoCard,
  StaticSubsectionTitle,
  StaticTag,
} from "./RightPanelStaticPrimitives";
import {
  FINAL_SECTION_STYLE,
  REPORTS_KNOWLEDGE_GRID_STYLE,
  SECTION_LIST_STYLE,
  SECTION_STYLE,
  TAG_LIST_STYLE,
} from "./rightPanelStaticSectionStyles";

export function CalendarSection() {
  return (
    <div style={SECTION_STYLE}>
      <ContextPanelSectionHeader icon={Calendar} title="经济日历" iconColor="var(--fg-5)" className="mb-2" />
      <CalendarColumnHeader />

      {CALENDAR_ITEMS.map((item) => (
        <CalendarDataRow
          key={`${item.time}-${item.event}`}
          time={item.time}
          event={item.event}
          impact={item.impact}
          change={item.change}
        />
      ))}
    </div>
  );
}

export function EventDynamicsSection() {
  return (
    <div style={SECTION_STYLE}>
      <ContextPanelSectionHeader icon={Zap} title="事件动态" iconColor="var(--fg-5)" className="mb-2" />
      <div style={SECTION_LIST_STYLE}>
        {EVENT_ITEMS.map((item) => (
          <StaticInfoCard
            key={`${item.category}-${item.title}`}
            accentColor={item.color}
            header={
              <span
                style={{
                  fontFamily: "var(--font-sans)",
                  fontWeight: 500,
                  fontSize: 8.5,
                  letterSpacing: "0.04em",
                  color: item.color,
                  padding: "1px 4px",
                  borderRadius: 2,
                  background: `${item.color}15`,
                }}
              >
                {item.category}
              </span>
            }
            badges={
              <div className="flex gap-1">
                <span
                  style={{
                    fontFamily: "var(--font-sans)",
                    fontWeight: 500,
                    fontSize: 8,
                    padding: "1px 4px",
                    borderRadius: 3,
                    border: `1px solid ${EVENT_IMPACT_COLOR[item.impact]}40`,
                    color: EVENT_IMPACT_COLOR[item.impact],
                    background: `${EVENT_IMPACT_COLOR[item.impact]}12`,
                  }}
                >
                  {EVENT_IMPACT_LABEL[item.impact]}
                </span>
                <span
                  style={{
                    fontFamily: "var(--font-sans)",
                    fontWeight: 500,
                    fontSize: 8,
                    padding: "1px 4px",
                    borderRadius: 3,
                    border: "1px solid var(--border)",
                    color: "var(--fg-5)",
                    background: "rgba(255,255,255,0.03)",
                  }}
                >
                  {item.pricing}
                </span>
              </div>
            }
          >
            {item.title}
          </StaticInfoCard>
        ))}
      </div>
    </div>
  );
}

export function ReportLinksSection() {
  return (
    <div>
      <StaticSubsectionTitle icon={FileText} title="报告" />
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {REPORT_ITEMS.map((item) => (
          <StaticCompactRow key={`${item.title}-${item.date}`} title={item.title} meta={item.date} />
        ))}
      </div>
    </div>
  );
}

export function KnowledgeTagsSection() {
  return (
    <div>
      <StaticSubsectionTitle icon={BookOpen} title="知识" />
      <div className="flex flex-wrap" style={TAG_LIST_STYLE}>
        {KNOWLEDGE_TAGS.map((tag) => (
          <StaticTag key={tag}>{tag}</StaticTag>
        ))}
      </div>
    </div>
  );
}

export function ReportsKnowledgeSection() {
  return (
    <div style={FINAL_SECTION_STYLE}>
      <div style={REPORTS_KNOWLEDGE_GRID_STYLE}>
        <ReportLinksSection />
        <KnowledgeTagsSection />
      </div>
    </div>
  );
}
