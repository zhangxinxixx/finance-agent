import { useMemo, useState } from "react";
import { useSchedulerOverview } from "@/hooks/useScheduler";
import {
  CATEGORY_LABELS, CATEGORY_COLORS, formatStatus, getStatusTone,
  formatFileSize, fetchRunDetail, fetchAgentAnalysis, agentAnalysisToTaskRun,
  type SchedulerCategoryStat, type SchedulerTaskRun,
  type SchedulerCronJob, type SchedulerOutputItem, type RunDetail, type AgentAnalysisItem,
  type SchedulerInputSourceMatrixItem, type SchedulerInputSourceSummary,
} from "@/adapters/scheduler";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FARuntimeLog, type FARuntimeLogEntry, type FARuntimeLogLevel } from "@/components/shared/FARuntimeLog";
import { Link } from "react-router-dom";
import {
  CheckCircle, XCircle, RefreshCw, Play, ChevronRight, ArrowRight,
  Dot, Search, Database, FileText, Gauge, GitBranch, Activity,
  Clock, Layers, X, ExternalLink, List,
} from "lucide-react";
import { triggerRunAllCollectors } from "@/adapters/scheduler";
import { useEffect } from "react";

// ═══════════════════════════════════════════════════════════════
//  TYPES & CONSTANTS
// ═══════════════════════════════════════════════════════════════

type DateRange = 1 | 7;
type CategoryFilter = string;

const STAGE_ORDER = ["collector", "parser", "features", "analysis", "renderer"] as const;
type PipelineStage = (typeof STAGE_ORDER)[number];

const STAGE_META: Record<PipelineStage, { label: string; color: string; icon: string }> = {
  collector:  { label: "采集", color: "#3b82f6", icon: "📡" },
  parser:     { label: "解析", color: "#f59e0b", icon: "🔧" },
  features:   { label: "特征", color: "#8b5cf6", icon: "📊" },
  analysis:   { label: "分析", color: "#10b981", icon: "🧠" },
  renderer:   { label: "输出", color: "#06b6d4", icon: "📄" },
};

function taskTypeToStage(taskType: string): PipelineStage {
  const t = taskType.toLowerCase();
  if (t.includes("collect") || t.includes("fetch") || t.includes("data") || ["technical", "positioning", "dxy", "treasury", "fed", "fred"].includes(t)) return "collector";
  if (t.includes("parse") || t.includes("extract") || t.includes("ocr")) return "parser";
  if (t.includes("feature") || t.includes("compute") || t.includes("calculate")) return "features";
  if (t.includes("analy") || t.includes("agent") || t.includes("regime") || t.includes("impact")) return "analysis";
  if (t.includes("render") || t.includes("report") || t.includes("output") || t.includes("generate") || t.includes("strategy")) return "renderer";
  return "analysis";
}

function matchesFilter(run: SchedulerTaskRun, category: CategoryFilter, query: string): boolean {
  if (category !== "all" && run.category !== category) return false;
  if (query.trim()) {
    const q = query.toLowerCase();
    return `${run.task_name} ${run.task_type} ${run.status}`.toLowerCase().includes(q);
  }
  return true;
}

function schedulerEventLevel(eventType: string): FARuntimeLogLevel {
  const value = eventType.toUpperCase();
  if (value.includes("FAILED") || value.includes("ERROR")) return "error";
  if (value.includes("BLOCKED") || value.includes("FALLBACK") || value.includes("DEGRADED")) return "warn";
  if (value.includes("FINISHED") || value.includes("SUCCESS") || value.includes("WRITTEN")) return "success";
  if (value.includes("STARTED") || value.includes("STATUS_CHANGED") || value.includes("EVALUATED")) return "info";
  return "debug";
}

function schedulerEventSource(event: RunDetail["events"][number]): string {
  const payload = event.payload ?? {};
  const stepName = typeof payload.step_name === "string" ? payload.step_name : null;
  const source = typeof payload.source === "string" ? payload.source : null;
  return stepName ?? event.task_id ?? source ?? "run";
}

function schedulerEventMessage(event: RunDetail["events"][number]): string {
  const payload = event.payload ?? {};
  const details = [
    typeof payload.reason === "string" ? payload.reason : null,
    typeof payload.blocked_reason === "string" ? payload.blocked_reason : null,
    typeof payload.error_message === "string" ? payload.error_message : null,
    typeof payload.from_status === "string" && typeof payload.to_status === "string"
      ? `${payload.from_status} -> ${payload.to_status}`
      : null,
  ].filter((item): item is string => Boolean(item));
  return details.length > 0 ? `${event.event_type} · ${details.join(" · ")}` : event.event_type;
}

function schedulerEventTime(value: string | null | undefined): string {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatSourceUpdateTime(value: string | null | undefined): string {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatSourceLogStatus(status: SchedulerInputSourceMatrixItem["task_log_status"]): string {
  if (status === "connected") return "任务已接入";
  if (status === "data_only") return "仅数据接入";
  return "等待接入";
}

function sourceLogTone(status: SchedulerInputSourceMatrixItem["task_log_status"]): string {
  if (status === "connected") return "var(--up)";
  if (status === "data_only") return "var(--warn)";
  return "var(--fg-5)";
}

const SOURCE_GROUP_LABELS: Record<string, string> = {
  macro: "宏观",
  cme: "CME",
  technical: "技术行情",
  positioning: "持仓",
  reports: "报告",
  news: "新闻事件",
};

const SOURCE_TYPE_LABELS: Record<string, string> = {
  api: "接口",
  pdf: "PDF",
  structured: "结构化",
  scraper: "抓取",
  mcp: "MCP 通道",
  calendar: "日历",
  webhook: "消息推送",
  rss: "订阅源",
};

const READINESS_LABELS: Record<string, string> = {
  ready: "已就绪",
  degraded: "降级可用",
  blocked: "阻塞",
  not_configured: "未配置",
};

const TASK_TYPE_LABELS: Record<string, string> = {
  macro_collect: "宏观采集",
  macro_feature: "宏观特征",
  report_render: "报告产出",
  fred: "FRED 采集",
  fed: "Fed 采集",
  treasury: "财政部采集",
  dxy: "DXY 采集",
  openbb: "OpenBB 补采",
  cme_download: "CME 下载",
  cme_parse: "CME 解析",
  cme_ingest: "CME 入库",
  option_wall: "期权墙计算",
  options_analysis: "期权分析",
  cme_options: "期权结构加工",
  technical: "技术行情处理",
  positioning: "持仓处理",
  cot: "COT 持仓采集",
  news_collect: "新闻采集",
  news_feature: "新闻特征",
  news_brief: "新闻摘要",
  report_analysis: "报告分析",
  jin10_report: "金十报告加工",
  flash_article_analysis: "快讯文章分析",
  jin10_refresh_jin10_flash: "金十快讯刷新",
  jin10_refresh_jin10_quotes: "金十行情刷新",
  jin10_refresh_jin10_kline: "金十 K 线刷新",
  jin10_refresh_jin10_calendar: "金十日历刷新",
  feishu: "飞书消息采集",
};

function formatSourceGroup(value: string): string {
  return SOURCE_GROUP_LABELS[value] ?? value;
}

function formatSourceType(value: string): string {
  return SOURCE_TYPE_LABELS[value] ?? value;
}

function formatReadinessState(value: string | null): string {
  if (!value) return "未知";
  return READINESS_LABELS[value] ?? value;
}

function formatTaskTypeLabel(value: string): string {
  return TASK_TYPE_LABELS[value] ?? value.split("_").join(" ");
}

function formatExpectedTasks(tasks: string[]): string {
  if (tasks.length === 0) return "未定义";
  const labels = tasks.map(formatTaskTypeLabel);
  if (labels.length <= 3) return labels.join(" / ");
  return `${labels.slice(0, 3).join(" / ")} +${labels.length - 3}`;
}

function formatRecentTasks(source: SchedulerInputSourceMatrixItem): string {
  if (source.latest_task_run?.task_name) return source.latest_task_run.task_name;
  if (source.recent_task_types.length > 0) return source.recent_task_types.map(formatTaskTypeLabel).join(" / ");
  return "暂无";
}

// ═══════════════════════════════════════════════════════════════
//  HEADER  — Stats + Controls
// ═══════════════════════════════════════════════════════════════

function HeaderBar({
  summary, onRefresh, onCollect, running,
  days, setDays, category, setCategory, categoryStats, query, setQuery,
}: {
  summary: any; onRefresh: () => void; onCollect: () => void; running: boolean;
  days: DateRange; setDays: (d: DateRange) => void;
  category: CategoryFilter; setCategory: (c: CategoryFilter) => void;
  categoryStats: Record<string, SchedulerCategoryStat>; query: string; setQuery: (q: string) => void;
}) {
  const ok = summary.data_sources_ok === summary.data_sources_total && summary.failed_count === 0;

  return (
    <div className="flex items-center gap-3 px-3 py-2" style={{ background: "var(--bg-card)", borderBottom: "1px solid var(--border-faint)" }}>
      <GitBranch size={14} className="text-[var(--brand-gold)] shrink-0" />
      <span className="text-[11px] font-bold text-[var(--fg-1)] tracking-wide shrink-0">调度中心</span>
      <div className="flex items-center gap-1 text-[9px] shrink-0">
        <span className={`w-1.5 h-1.5 rounded-full ${ok ? "bg-[var(--up)]" : "bg-[var(--down)]"}`} />
        <span className="text-[var(--fg-4)]">{ok ? "正常" : "异常"}</span>
      </div>
      <Link to="/scheduler/tasks" className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-0.5 text-[8px] text-[var(--fg-4)] hover:text-[var(--brand)] hover:border-[var(--brand-gold)] transition-colors shrink-0">
        <List size={9} />
        任务清单
        <ChevronRight size={9} />
      </Link>
      <Link to="/scheduler/dag" className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-2 py-0.5 text-[8px] text-[var(--fg-4)] hover:text-[var(--brand)] hover:border-[var(--brand-gold)] transition-colors shrink-0">
        <Activity size={9} />
        流程图
        <ChevronRight size={9} />
      </Link>
      <div className="w-px h-4 bg-[var(--border-faint)]" />
      <div className="flex items-center gap-3 text-[9px] shrink-0">
        {[{ l: "今日", v: summary.today_runs, c: "var(--fg-2)" }, { l: "成功", v: summary.success_count, c: "var(--up)" }, { l: "失败", v: summary.failed_count, c: summary.failed_count > 0 ? "var(--down)" : "var(--fg-4)" }, { l: "数据源", v: `${summary.data_sources_ok}/${summary.data_sources_total}`, c: "var(--up)" }].map(({ l, v, c }) => (
          <div key={l} className="flex items-center gap-1">
            <span className="text-[var(--fg-5)]">{l}</span>
            <span className="font-semibold" style={{ color: c }}>{v}</span>
          </div>
        ))}
      </div>
      <div className="flex-1" />
      <div className="flex items-center gap-0.5 rounded border border-[var(--border)] p-0.5">
        {[{ v: 1, l: "今天" }, { v: 7, l: "7天" }].map(r => (
          <button key={r.v} onClick={() => setDays(r.v as DateRange)} className={`rounded px-2 py-0.5 text-[8px] font-semibold ${days === r.v ? "bg-[var(--bg-active)]" : "text-[var(--fg-5)]"}`}>{r.l}</button>
        ))}
      </div>
      <div className="flex items-center gap-1 rounded border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 py-1 w-[140px]">
        <Search size={10} className="text-[var(--fg-6)]" />
        <input type="text" placeholder="搜索任务..." value={query} onChange={e => setQuery(e.target.value)} className="flex-1 bg-transparent text-[9px] text-[var(--fg-3)] outline-none" />
      </div>
      <button onClick={onCollect} disabled={running} className="inline-flex items-center gap-1 rounded border border-[var(--brand-gold)] bg-[var(--color-gold-subtle)] px-2 py-1 text-[9px] font-semibold text-[var(--brand-gold)] hover:bg-[var(--brand-gold)] hover:text-black disabled:opacity-50">
        {running ? <RefreshCw size={10} className="animate-spin" /> : <Play size={10} />}采集
      </button>
      <button onClick={onRefresh} className="rounded border border-[var(--border)] px-2 py-1 text-[9px] text-[var(--fg-4)]"><RefreshCw size={10} /></button>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  STATUS LEGEND  — Airflow-style legend bar
// ═══════════════════════════════════════════════════════════════

function StatusLegend({ stats }: { stats: Record<string, SchedulerCategoryStat> }) {
  const entries = Object.entries(stats).filter(([, s]) => s.total > 0);
  if (!entries.length) return null;
  return (
    <div className="flex items-center gap-3 px-3 py-1.5 text-[8px]" style={{ background: "var(--bg-panel)", borderBottom: "1px solid var(--border-faint)" }}>
      <span className="text-[var(--fg-5)] font-semibold">分类统计</span>
      {entries.map(([k, s]) => {
        const color = CATEGORY_COLORS[k] ?? "#94a3b8";
        const label = CATEGORY_LABELS[k] ?? k;
        const pct = s.total > 0 ? Math.round((s.success / s.total) * 100) : 0;
        return (
          <div key={k} className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-sm" style={{ background: color }} />
            <span className="text-[var(--fg-3)]">{label}</span>
            <span className="font-mono text-[var(--fg-5)]">{s.success}/{s.total}</span>
            <div className="w-10 h-1 rounded-full bg-[var(--bg-card-inner)] overflow-hidden">
              <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  PIPELINE GRID  — GitLab CI + dbt lineage hybrid
// ═══════════════════════════════════════════════════════════════

function PipelineGrid({
  runs, onSelectRun, selectedRunId,
}: {
  runs: SchedulerTaskRun[]; onSelectRun: (id: string) => void; selectedRunId: string | null;
}) {
  // Group by date
  const byDate = new Map<string, SchedulerTaskRun[]>();
  for (const r of runs) {
    const d = r.trade_date || "日期未知";
    if (!byDate.has(d)) byDate.set(d, []);
    byDate.get(d)!.push(r);
  }
  const dates = [...byDate.keys()].sort((a, b) => b.localeCompare(a));

  if (!dates.length) return <FAEmptyState title="暂无数据" description="点击「采集」运行数据采集器" className="py-16" />;

  return (
    <div className="flex-1 overflow-auto">
      {/* Stage header row */}
      <div className="flex items-stretch sticky top-0 z-10" style={{ background: "var(--bg-panel)", borderBottom: "2px solid var(--border)" }}>
        {/* Date label column */}
        <div className="shrink-0 w-[120px] flex items-end px-3 pb-1.5">
          <span className="text-[8px] font-semibold text-[var(--fg-5)] uppercase tracking-wider">交易日</span>
        </div>
        {/* Stage columns */}
        <div className="flex flex-1 min-w-0">
          {STAGE_ORDER.map((stage, i) => {
            const m = STAGE_META[stage];
            const isLast = i === STAGE_ORDER.length - 1;
            return (
              <div key={stage} className="flex-1 min-w-[140px] px-2 py-1.5 border-l border-[var(--border-faint)]">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs">{m.icon}</span>
                  <span className="text-[9px] font-bold" style={{ color: m.color }}>{m.label}</span>
                  {!isLast && (
                    <ArrowRight size={10} className="ml-auto text-[var(--fg-6)]" />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Date rows */}
      {dates.map(date => {
        const dateRuns = byDate.get(date)!;
        // Group by stage
        const stageMap = new Map<PipelineStage, SchedulerTaskRun[]>();
        for (const r of dateRuns) {
          const s = taskTypeToStage(r.task_type);
          if (!stageMap.has(s)) stageMap.set(s, []);
          stageMap.get(s)!.push(r);
        }

        return (
          <div key={date} className="flex items-stretch group" style={{ borderBottom: "1px solid var(--border-faint)", minHeight: "56px" }}>
            {/* Date label */}
            <div className="shrink-0 w-[120px] flex flex-col justify-center px-3 bg-[var(--bg-card)] group-hover:bg-[var(--bg-card-inner)] transition-colors">
              <span className="text-[10px] font-mono font-semibold text-[var(--fg-2)]">{date}</span>
              <span className="text-[7px] text-[var(--fg-5)]">{dateRuns.length} 任务</span>
            </div>

            {/* Stage cells */}
            <div className="flex flex-1 min-w-0">
              {STAGE_ORDER.map((stage, i) => {
                const stageRuns = stageMap.get(stage) || [];
                const m = STAGE_META[stage];
                const isLast = i === STAGE_ORDER.length - 1;
                const nextStage = !isLast ? STAGE_ORDER[i + 1] : null;
                const nextRuns = nextStage ? (stageMap.get(nextStage) || []) : [];
                // 当前阶段有任务且下一阶段也有任务时才画连线
                const hasFlow = stageRuns.length > 0 && nextRuns.length > 0;

                return (
                  <>
                    <div className="flex-1 min-w-[140px] p-1.5 border-l border-[var(--border-faint)] bg-[var(--bg-card)] group-hover:bg-[var(--bg-card-inner)] transition-colors relative">
                      {stageRuns.length === 0 ? (
                        <div className="h-full flex items-center justify-center">
                          <div className="w-2 h-2 rounded-full bg-[var(--border-faint)]" title="无任务" />
                        </div>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {stageRuns.map(run => {
                            const tone = getStatusTone(run.status);
                            const isSelected = selectedRunId === run.run_id;
                            const dotColor = tone === "up" ? "var(--up)" : tone === "down" ? "var(--down)" : tone === "warn" ? "var(--warn)" : "var(--fg-5)";
                            const bg = tone === "up" ? "var(--color-up-subtle)" : tone === "down" ? "var(--color-down-subtle)" : "var(--bg-card-inner)";

                            return (
                              <button
                                key={run.run_id}
                                onClick={() => onSelectRun(run.run_id)}
                                className="flex items-center gap-1 rounded px-1.5 py-1 text-left border transition-all hover:scale-[1.02] w-full"
                                style={{
                                  borderColor: isSelected ? m.color : "var(--border-faint)",
                                  background: isSelected ? `${m.color}10` : bg,
                                  boxShadow: isSelected ? `0 0 0 1px ${m.color}40` : "none",
                                }}
                              >
                                <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: dotColor }} />
                                <div className="min-w-0 flex-1">
                                  <div className="text-[9px] font-medium text-[var(--fg-2)] truncate leading-tight">{run.task_name}</div>
                                  <div className="text-[7px] text-[var(--fg-5)] truncate">{formatTaskTypeLabel(run.task_type)}</div>
                                </div>
                                {isSelected && <ChevronRight size={10} className="text-[var(--fg-5)] shrink-0" />}
                              </button>
                            );
                          })}
                        </div>
                      )}
                      {/* 数据流箭头 → 下一阶段 */}
                      {hasFlow && (
                        <ArrowRight size={12} className="absolute -right-[12px] top-1/2 -translate-y-1/2 text-[var(--brand-gold)]/40 z-10" />
                      )}
                    </div>
                  </>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  TASK DETAIL DRAWER  — Prefect-style slide-out panel
// ═══════════════════════════════════════════════════════════════

function TaskDetailDrawer({ runId, runType, onClose }: { runId: string; runType: "task" | "agent"; onClose: () => void }) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(runType === "task");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (runType === "agent") { setLoading(false); return; }
    setLoading(true); setError(null);
    fetchRunDetail(runId).then(setDetail).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [runId, runType]);

  return (
    <div className="shrink-0 border-l border-[var(--border)] bg-[var(--bg-card)] overflow-auto" style={{ width: "380px" }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-faint)] sticky top-0 bg-[var(--bg-card)] z-10">
        <h3 className="text-[10px] font-bold text-[var(--fg-2)] flex-1 truncate">任务详情</h3>
        {runType !== "agent" && (
        <a
          href={`/agent-tasks/${runId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded border border-[var(--border)] px-1.5 py-0.5 text-[8px] text-[var(--fg-4)] hover:text-[var(--brand)] hover:border-[var(--brand)]/30 transition-colors shrink-0"
        >
          全屏 <ExternalLink size={9} />
        </a>
        )}
        <button onClick={onClose} className="rounded p-0.5 hover:bg-[var(--bg-hover)] text-[var(--fg-5)]"><X size={12} /></button>
      </div>

      {/* Content */}
      <div className="p-3">
        {loading && <div className="flex justify-center py-8"><RefreshCw size={16} className="animate-spin text-[var(--fg-5)]" /></div>}
        {error && <div className="text-[10px] text-[var(--down)] py-4 text-center">{error}</div>}
        {runType === "agent" && !loading && (
          <div className="space-y-3 text-[9px]">
            <div className="rounded border border-[var(--border-faint)] px-2 py-1.5 bg-[var(--bg-card-inner)]">
              <span className="text-[7px] text-[var(--fg-6)] uppercase">来源</span>
              <div className="font-semibold text-[var(--fg-2)]">智能体分析产出</div>
              <div className="text-[var(--fg-5)] mt-0.5">此条目为智能体分析产出，非任务管线调度条目</div>
            </div>
          </div>
        )}

        {detail && (
          <div className="space-y-3 text-[9px]">
            {/* Meta grid */}
            <div className="grid grid-cols-2 gap-1.5">
              {[
                { l: "运行 ID", v: detail.run_id.slice(0, 12) + "..." },
                { l: "类型", v: formatTaskTypeLabel(detail.task_type) },
                { l: "状态", v: detail.status },
                { l: "交易日", v: detail.trade_date || "—" },
                { l: "耗时", v: (detail.started_at && detail.ended_at ? ((new Date(detail.ended_at).getTime() - new Date(detail.started_at).getTime()) / 1000).toFixed(1) + "s" : "—") },
                { l: "步骤数", v: `${detail.steps.length}` },
              ].map(({ l, v }) => (
                <div key={l} className="rounded border border-[var(--border-faint)] px-2 py-1">
                  <div className="text-[7px] text-[var(--fg-6)] uppercase mb-0.5">{l}</div>
                  <div className="font-mono font-semibold text-[var(--fg-2)] truncate">{v}</div>
                </div>
              ))}
            </div>

            {/* Error banner */}
            {detail.error && (
              <div className="rounded border border-[var(--down)]/20 bg-[var(--down)]/5 px-2 py-1.5 text-[8px] text-[var(--down)]">
                {detail.error_summary || detail.error}
              </div>
            )}

            {/* Steps pipeline */}
            {detail.steps.length > 0 && (
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <Layers size={10} className="text-[var(--fg-5)]" />
                  <span className="text-[8px] font-semibold text-[var(--fg-4)] uppercase">执行步骤</span>
                </div>
                <div className="space-y-2">
                  {detail.steps.map((step, idx) => {
                    const sc = (() => {
                      const s = step.status.toLowerCase();
                      if (s === "success") return "var(--up)";
                      if (s === "failed") return "var(--down)";
                      if (s === "running") return "var(--warn)";
                      return "var(--fg-5)";
                    })();
                    const taskName = step.name || (step as any).task_name || `步骤 ${idx + 1}`;
                    const allRefs = [...(step.source_refs || []), ...(step.input_refs || []), ...(step.output_refs || []), ...((step as any).artifact_refs || [])];

                    return (
                      <div key={step.step_id || idx} className="flex gap-2">
                        {/* Step connector */}
                        <div className="flex flex-col items-center">
                          <div className="w-2 h-2 rounded-full shrink-0 mt-1" style={{ background: sc }} />
                          {idx < detail.steps.length - 1 && <div className="w-px flex-1 mt-1" style={{ background: "var(--border-faint)" }} />}
                        </div>
                        {/* Step card */}
                        <div className="flex-1 rounded border px-2 py-1.5 min-w-0" style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}>
                          <div className="flex items-center gap-1.5 mb-1">
                            <span className="text-[8px] font-semibold text-[var(--fg-2)] truncate">{taskName}</span>
                            {step.stage && <span className="text-[7px] text-[var(--fg-6)]">[{formatTaskTypeLabel(step.stage)}]</span>}
                            <span className="flex-1" />
                            <div className="w-1.5 h-1.5 rounded-full" style={{ background: sc }} />
                          </div>

                          {/* Refs */}
                          {allRefs.length > 0 && (
                            <div className="space-y-0.5 text-[7px]">
                              {step.source_refs && step.source_refs.length > 0 && (
                                <div className="text-[var(--fg-5)]">
                                  <span className="text-[var(--fg-6)]">📥 来源:</span>
                                  {step.source_refs.slice(0, 3).map((r: any, i: number) => <div key={i} className="ml-2 truncate font-mono">{r.path || r.name || r.url || JSON.stringify(r)}</div>)}
                                </div>
                              )}
                              {step.output_refs && step.output_refs.length > 0 && (
                                <div className="text-[var(--brand)]">
                                  <span className="text-[var(--fg-6)]">↓ 产出:</span>
                                  {step.output_refs.slice(0, 3).map((r: any, i: number) => <div key={i} className="ml-2 truncate font-mono">{r.path || r.name || JSON.stringify(r)}</div>)}
                                </div>
                              )}
                              {((step as any).artifact_refs) && ((step as any).artifact_refs).length > 0 && (
                                <div className="text-[var(--warn)]">
                                  <span className="text-[var(--fg-6)]">📦 产物:</span>
                                  {((step as any).artifact_refs).slice(0, 3).map((r: any, i: number) => <div key={i} className="ml-2 truncate font-mono">{r.path || r.name || JSON.stringify(r)}</div>)}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {detail.events.length > 0 && (
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <Activity size={10} className="text-[var(--fg-5)]" />
                  <span className="text-[8px] font-semibold text-[var(--fg-4)] uppercase">事件时间线</span>
                  <span className="text-[7px] text-[var(--fg-6)]">{detail.events.length} 条</span>
                </div>
                <FARuntimeLog
                  className="max-h-[220px] overflow-y-auto"
                  emptyText="暂无事件时间线"
                  entries={detail.events.map((event): FARuntimeLogEntry => ({
                    id: event.id,
                    time: schedulerEventTime(event.created_at),
                    level: schedulerEventLevel(event.event_type),
                    source: schedulerEventSource(event),
                    message: schedulerEventMessage(event),
                  }))}
                />
              </div>
            )}

            {/* Empty steps */}
            {detail.steps.length === 0 && detail.events.length === 0 && (
              <div className="text-[8px] text-[var(--fg-5)] text-center py-3">暂无步骤或事件数据</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  MAIN PAGE
// ═══════════════════════════════════════════════════════════════

export function SchedulerCenterPage() {
  const [days, setDays] = useState<DateRange>(7);
  const [category] = useState<CategoryFilter>("all");
  const [query, setQuery] = useState("");
  const [runningCollectors, setRunningCollectors] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRunType, setSelectedRunType] = useState<"task" | "agent">("task");
  const [agentRuns, setAgentRuns] = useState<SchedulerTaskRun[]>([]);
  const { data, isLoading, isError, error, refresh } = useSchedulerOverview(days);

  // 拉取 Agent Analysis 数据并合并为管线任务（后端按 trade_date 参数被忽略，取一次即可）
  useEffect(() => {
    if (!data) return;
    // 只拉一次最新 30 天的 agent 分析
    fetchAgentAnalysis("latest").then(items => {
      const merged = items.filter(a => a.agent_name).map(agentAnalysisToTaskRun);
      setAgentRuns(merged);
    }).catch(() => {});
  }, [data]);

  async function handleCollect() {
    setRunningCollectors(true);
    try { await triggerRunAllCollectors(); setTimeout(() => { refresh(); setRunningCollectors(false); }, 5000); }
    catch { setRunningCollectors(false); }
  }

  function handleSelectRun(runId: string) {
    const isAgent = agentRuns.some(r => r.run_id === runId);
    setSelectedRunId(runId);
    setSelectedRunType(isAgent ? "agent" : "task");
  }

  const filteredRuns = useMemo(() => {
    if (!data) return [];
    // Date cutoff based on selected range
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    const cutoffStr = cutoff.toISOString().slice(0, 10);
    const byDate = (r: SchedulerTaskRun) => {
      if (!r.trade_date) return true; // 无日期的任务保留
      return r.trade_date >= cutoffStr;
    };
    const taskRuns = data.task_runs.filter(r => matchesFilter(r, category, query) && byDate(r));
    const agentFiltered = agentRuns.filter(r => matchesFilter(r, category, query) && byDate(r));

    // 去重：同一 (日期, 任务类型) 只保留最新一条（按 started_at 降序）
    function dedupByDateType(runs: SchedulerTaskRun[]): SchedulerTaskRun[] {
      const seen = new Map<string, SchedulerTaskRun>();
      // 先按 started_at 降序排列，保证最新在前
      const sorted = [...runs].sort((a, b) => {
        const ta = a.started_at ?? "";
        const tb = b.started_at ?? "";
        return tb.localeCompare(ta);
      });
      for (const r of sorted) {
        const key = `${r.trade_date || "nodate"}::${r.task_type}`;
        if (!seen.has(key)) seen.set(key, r);
      }
      return [...seen.values()];
    }

    const dedupedTasks = dedupByDateType(taskRuns);
    const dedupedAgents = dedupByDateType(agentFiltered);
    const taskIds = new Set(dedupedTasks.map(r => r.run_id));
    const uniqueAgent = dedupedAgents.filter(r => !taskIds.has(r.run_id));
    return [...dedupedTasks, ...uniqueAgent];
  }, [data, category, query, agentRuns, days]);

  if (isLoading)
    return <PageShell><div className="flex justify-center py-20"><RefreshCw size={20} className="animate-spin text-[var(--fg-5)]" /></div></PageShell>;
  if (isError)
    return <PageShell><div className="flex flex-col items-center py-20"><XCircle size={28} className="text-[var(--down)] mb-2" /><span className="text-sm text-[var(--fg-3)]">{error?.message ?? "加载失败"}</span><button onClick={refresh} className="mt-2 rounded border px-3 py-1 text-xs">重试</button></div></PageShell>;
  if (!data) return null;

  const { summary, category_stats, data_source_status, cron_jobs, artifacts_summary } = data;

  return (
    <PageShell>
      <HeaderBar summary={summary} onRefresh={refresh} onCollect={handleCollect} running={runningCollectors} days={days} setDays={setDays} category={category} setCategory={() => {}} categoryStats={category_stats} query={query} setQuery={setQuery} />
      <StatusLegend stats={category_stats} />

      <div className="flex-1 flex min-h-0">
        {/* Pipeline grid (left) */}
        <div className="flex-1 flex flex-col min-w-0">
          <PipelineGrid runs={filteredRuns} onSelectRun={setSelectedRunId} selectedRunId={selectedRunId} />
        </div>

        {/* Detail drawer (right, when selected) */}
        {selectedRunId && <TaskDetailDrawer runId={selectedRunId} runType={selectedRunType} onClose={() => setSelectedRunId(null)} />}

        {/* Sidebar (right, when no selection) */}
        {!selectedRunId && (
          <div className="shrink-0 border-l border-[var(--border-faint)] overflow-auto" style={{ width: "360px", background: "var(--bg-panel)" }}>
            <SidePanel
              dataSource={data_source_status}
              sourceSummary={data.input_source_summary}
              sourceMatrix={data.input_source_matrix}
              cronJobs={cron_jobs}
              outputs={artifacts_summary.recent_outputs}
            />
          </div>
        )}
      </div>
    </PageShell>
  );
}

function SidePanel({
  dataSource,
  sourceSummary,
  sourceMatrix,
  cronJobs,
  outputs,
}: {
  dataSource: any;
  sourceSummary: SchedulerInputSourceSummary;
  sourceMatrix: SchedulerInputSourceMatrixItem[];
  cronJobs: SchedulerCronJob[];
  outputs: SchedulerOutputItem[];
}) {
  return (
    <div className="flex flex-col gap-3 p-2.5">
      <div className="rounded border border-[var(--border-faint)] bg-[var(--bg-card)] p-2.5">
        <div className="flex items-center gap-1.5 mb-2"><Database size={10} className="text-[var(--fg-5)]" /><span className="text-[9px] font-semibold text-[var(--fg-3)]">数据源</span></div>
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1 rounded-full bg-[var(--bg-card-inner)]"><div className="h-full rounded-full bg-[var(--up)]" style={{ width: `${(dataSource.ok / Math.max(dataSource.total, 1)) * 100}%` }} /></div>
          <span className="text-[8px] font-semibold text-[var(--up)]">{dataSource.ok}/{dataSource.total}</span>
        </div>
      </div>
      <div className="rounded border border-[var(--border-faint)] bg-[var(--bg-card)] p-2.5">
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-1.5">
            <Gauge size={10} className="text-[var(--fg-5)]" />
            <span className="text-[9px] font-semibold text-[var(--fg-3)]">输入源接入矩阵</span>
          </div>
          <span className="text-[8px] text-[var(--fg-5)]">{sourceSummary.total} 个源</span>
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          {[
            { label: "任务已接入", value: sourceSummary.connected, color: "var(--up)" },
            { label: "仅数据接入", value: sourceSummary.data_only, color: "var(--warn)" },
            { label: "等待接入", value: sourceSummary.waiting, color: "var(--fg-4)" },
          ].map((item) => (
            <div key={item.label} className="rounded border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1.5">
              <div className="text-[7px] text-[var(--fg-6)]">{item.label}</div>
              <div className="mt-0.5 text-[10px] font-semibold" style={{ color: item.color }}>{item.value}</div>
            </div>
          ))}
        </div>
        <div className="mt-2.5 space-y-2 max-h-[540px] overflow-y-auto pr-1">
          {sourceMatrix.map((source) => {
            const tone = sourceLogTone(source.task_log_status);
            return (
              <div key={source.source_key} className="rounded border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                <div className="flex items-start gap-2">
                  <div className="mt-1 h-2 w-2 rounded-full shrink-0" style={{ background: tone }} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[9px] font-semibold text-[var(--fg-2)]">{source.source_label}</span>
                      <span className="rounded px-1.5 py-px text-[7px] font-semibold" style={{ background: `${tone}14`, color: tone }}>
                        {formatSourceLogStatus(source.task_log_status)}
                      </span>
                    </div>
                    <div className="mt-1 text-[7px] text-[var(--fg-5)]">
                      {formatSourceGroup(source.source_group)} · {formatSourceType(source.source_type)}
                    </div>
                    <div className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-1 text-[7px] text-[var(--fg-4)]">
                      <div>最新数据：{formatSourceUpdateTime(source.latest_update_time)}</div>
                      <div>就绪状态：{formatReadinessState(source.readiness_state)}</div>
                      <div className="col-span-2">预期任务：{formatExpectedTasks(source.expected_task_types)}</div>
                      <div className="col-span-2">最近任务：{formatRecentTasks(source)}</div>
                    </div>
                    {source.notes && (
                      <div className="mt-1.5 line-clamp-2 text-[7px] text-[var(--fg-5)]">{source.notes}</div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {cronJobs.length > 0 && (
        <div className="rounded border border-[var(--border-faint)] bg-[var(--bg-card)] p-2.5">
          <div className="flex items-center gap-1.5 mb-2"><Clock size={10} className="text-[var(--fg-5)]" /><span className="text-[9px] font-semibold text-[var(--fg-3)]">定时任务</span></div>
          {cronJobs.map(j => (
            <div key={j.name} className="flex items-center gap-1.5 text-[8px] mb-1">
              <div className={`w-1 h-1 rounded-full ${j.enabled ? "bg-[var(--up)]" : "bg-[var(--fg-5)]"}`} />
              <span className="flex-1 truncate text-[var(--fg-3)]">{j.name}</span>
            </div>
          ))}
        </div>
      )}
      {outputs.length > 0 && (
        <div className="rounded border border-[var(--border-faint)] bg-[var(--bg-card)] p-2.5">
          <div className="flex items-center gap-1.5 mb-2"><FileText size={10} className="text-[var(--fg-5)]" /><span className="text-[9px] font-semibold text-[var(--fg-3)]">最近产出</span></div>
          {outputs.slice(0, 8).map(o => (
            <div key={o.path} className="flex items-center gap-1 text-[7px] mb-0.5"><span className="flex-1 truncate text-[var(--fg-4)]">{o.name}</span><span className="text-[var(--fg-6)]">{formatFileSize(o.size)}</span></div>
          ))}
        </div>
      )}
    </div>
  );
}

function PageShell({ children }: { children: React.ReactNode }) {
  return <div className="finance-page-shell flex flex-col h-full">{children}</div>;
}

export default SchedulerCenterPage;
