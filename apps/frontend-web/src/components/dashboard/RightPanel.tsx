import type { DashboardSummary, DashboardViewModel } from "@/types/dashboard";
import type { SourceRef } from "@/types/common";
import { FAStatusPill } from "@/components/shared/FAStatusPill";

interface RightPanelProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
  sourceRefs?: SourceRef[];
}

function toTone(status: string | null | undefined): "up" | "warn" | "down" | "info" | "dim" {
  switch (String(status ?? "").toLowerCase()) {
    case "available":
    case "ok":
    case "ready":
    case "live":
    case "done":
      return "up";
    case "partial":
    case "warn":
    case "warning":
    case "mock":
    case "pending":
      return "warn";
    case "running":
      return "info";
    case "error":
    case "failed":
    case "unavailable":
    case "missing":
      return "down";
    default:
      return "dim";
  }
}

export function RightPanel({ summary, viewModel }: RightPanelProps) {
  const { recent_tasks, latest_reports, data_source_status } = summary;
  const modules = viewModel?.modules ?? [];

  return (
    <div className="space-y-3">
      {/* Today's Tasks */}
      <div className="fa-card">
        <div className="fa-card-header">
          <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] bg-[var(--brand)]" />
          <div className="min-w-0 flex-1">
            <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Today Tasks</div>
            <div className="truncate text-[12px] font-semibold leading-none text-[var(--fg-2)]">今日任务进度</div>
          </div>
        </div>
        <div className="fa-card-body space-y-2">
          {recent_tasks.length > 0 ? recent_tasks.map((task) => (
            <div key={`${task.title}-${task.status}`} className="flex items-center justify-between gap-2 border-b border-white/[0.04] pb-1.5 last:border-b-0 last:pb-0">
              <div className="min-w-0">
                <div className="truncate text-[11px] font-medium text-[var(--fg-2)]">{task.title}</div>
                {task.detail ? <div className="mt-0.5 truncate text-[9px] text-[var(--fg-5)]">{task.detail}</div> : null}
              </div>
              <FAStatusPill
                tone={
                  task.status === "done" ? "up"
                    : task.status === "running" ? "info"
                      : task.status === "failed" ? "down"
                        : "warn"
                }
              >
                {task.status}
              </FAStatusPill>
            </div>
          )) : (
            <div className="text-[11px] text-[var(--fg-5)]">暂无任务</div>
          )}
        </div>
      </div>

      {/* Data Sources */}
      <div className="fa-card">
        <div className="fa-card-header">
          <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] bg-[var(--info)]" />
          <div className="min-w-0 flex-1">
            <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Data Status</div>
            <div className="truncate text-[12px] font-semibold leading-none text-[var(--fg-2)]">数据源状态</div>
          </div>
        </div>
        <div className="fa-card-body space-y-1.5">
          {Object.values(data_source_status).map((src) => (
            <div key={src.label} className="flex items-center justify-between gap-2 text-[10px]">
              <span className="truncate text-[var(--fg-3)]">{src.label}</span>
              <FAStatusPill tone={toTone(src.status)} dot={false}>{src.status}</FAStatusPill>
            </div>
          ))}
          {modules.length > 0 ? (
            <div className="mt-1.5 border-t border-white/[0.04] pt-1.5">
              <div className="text-[8px] font-semibold uppercase tracking-[0.06em] text-[var(--fg-5)] mb-1">Modules</div>
              {modules.slice(0, 6).map((mod) => (
                <div key={mod.id} className="flex items-center justify-between gap-2 text-[10px]">
                  <span className="truncate text-[var(--fg-3)]">{mod.label}</span>
                  <FAStatusPill tone={toTone(mod.status)} dot={false}>{mod.status}</FAStatusPill>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      {/* Latest Reports */}
      <div className="fa-card">
        <div className="fa-card-header">
          <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] bg-[var(--up)]" />
          <div className="min-w-0 flex-1">
            <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Latest Reports</div>
            <div className="truncate text-[12px] font-semibold leading-none text-[var(--fg-2)]">最新报告</div>
          </div>
        </div>
        <div className="fa-card-body space-y-1.5">
          {latest_reports.length > 0 ? latest_reports.slice(0, 5).map((report) => (
            <div key={`${report.title}-${report.trade_date}`} className="flex items-center justify-between gap-2 border-b border-white/[0.04] pb-1.5 last:border-b-0 last:pb-0">
              <div className="min-w-0">
                <div className="truncate text-[11px] font-medium text-[var(--fg-2)]">{report.title}</div>
                <div className="mt-0.5 text-[9px] text-[var(--fg-5)]">{report.trade_date}</div>
              </div>
              <FAStatusPill
                tone={report.status === "ready" ? "up" : report.status === "pending" ? "warn" : "down"}
              >
                {report.status}
              </FAStatusPill>
            </div>
          )) : (
            <div className="text-[11px] text-[var(--fg-5)]">暂无输出</div>
          )}
        </div>
      </div>
    </div>
  );
}
