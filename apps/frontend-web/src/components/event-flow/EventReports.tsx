import { FileText } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import type { EventFlowReportItem } from "@/types/event-flow";

interface EventReportsProps {
  reports: EventFlowReportItem[];
}

export function EventReports({ reports }: EventReportsProps) {
  return (
    <FACard
      title={
        <div className="flex items-center gap-2">
          <FileText size={12} className="text-[var(--brand-hover)]" />
          <span>报告生成与分析</span>
        </div>
      }
      eyebrow="Reports"
      accent="brand"
    >
      {reports.length === 0 ? (
        <FAEmptyState title="暂无报告" description="当前没有可生成的报告。" className="p-4" />
      ) : (
        <div className="grid grid-cols-2 gap-[6px]">
          {reports.map((report) => (
            <button
              key={report.title}
              type="button"
              className="cursor-pointer rounded-[4px] border px-[10px] py-[8px] text-left transition-colors hover:brightness-110"
              style={{
                background: `${report.color}0f`,
                borderColor: `${report.color}2e`,
              }}
            >
              <div className="mb-1 flex items-center gap-[6px]">
                <div
                  className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-[4px] border"
                  style={{
                    background: `${report.color}22`,
                    borderColor: `${report.color}3a`,
                  }}
                >
                  <FileText size={11} style={{ color: report.color }} />
                </div>
                <span className="text-[11px] font-semibold leading-[1.3] text-[var(--fg-2)]">{report.title}</span>
              </div>
              <div className="pl-[28px] text-[10px] leading-[1.4] text-[var(--fg-5)]">{report.desc}</div>
            </button>
          ))}
        </div>
      )}
    </FACard>
  );
}
