import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useSchedulerOverview } from "@/hooks/useScheduler";
import {
  CATEGORY_LABELS, CATEGORY_COLORS, formatStatus, getStatusTone,
  type SchedulerTaskRun,
} from "@/adapters/scheduler";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import {
  CheckCircle, XCircle, RefreshCw, Search, ChevronUp, ChevronDown,
  ArrowLeft, GitBranch, ExternalLink, Dot,
} from "lucide-react";

type SortField = "task_name" | "task_type" | "trade_date" | "status" | "started_at" | "step_count";
type SortDir = "asc" | "desc";
type StatusFilter = "all" | "success" | "failed" | "running" | "pending";

// ── Helpers ──

function statusFilterOptions(): { value: StatusFilter; label: string }[] {
  return [
    { value: "all", label: "全部" },
    { value: "success", label: "成功" },
    { value: "failed", label: "失败" },
    { value: "running", label: "运行中" },
    { value: "pending", label: "等待中" },
  ];
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

// ═══════════════════════════════════════════════════════════════
//  HEADER
// ═══════════════════════════════════════════════════════════════

function ListHeader({
  query, setQuery, statusFilter, setStatusFilter,
  sortField, sortDir, onSort,
  onRefresh,
}: {
  query: string; setQuery: (q: string) => void;
  statusFilter: StatusFilter; setStatusFilter: (s: StatusFilter) => void;
  sortField: SortField; sortDir: SortDir; onSort: (f: SortField) => void;
  onRefresh: () => void;
}) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 border-b border-[var(--border-faint)]" style={{ background: "var(--bg-card)" }}>
      <Link to="/scheduler" className="flex items-center gap-1 text-[var(--fg-4)] hover:text-[var(--fg-2)] transition-colors">
        <ArrowLeft size={14} />
      </Link>
      <GitBranch size={14} className="text-[var(--brand-gold)]" />
      <span className="text-[11px] font-bold text-[var(--fg-1)] tracking-wide">任务清单</span>

      <div className="w-px h-4 bg-[var(--border-faint)]" />

      {/* Status filter pills */}
      <div className="flex items-center gap-0.5 rounded border border-[var(--border)] p-0.5">
        {statusFilterOptions().map(o => (
          <button
            key={o.value}
            onClick={() => setStatusFilter(o.value)}
            className={`rounded px-2 py-0.5 text-[8px] font-semibold ${statusFilter === o.value ? "bg-[var(--bg-active)] text-[var(--brand-hover)]" : "text-[var(--fg-5)]"}`}
          >
            {o.label}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="flex items-center gap-1 rounded border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 py-1 w-[160px] ml-auto">
        <Search size={10} className="text-[var(--fg-6)]" />
        <input type="text" placeholder="搜索..." value={query} onChange={e => setQuery(e.target.value)} className="flex-1 bg-transparent text-[9px] text-[var(--fg-3)] outline-none" />
      </div>

      <button onClick={onRefresh} className="rounded border border-[var(--border)] px-2 py-1 text-[9px] text-[var(--fg-4)]">
        <RefreshCw size={10} />
      </button>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  SORT ICON
// ═══════════════════════════════════════════════════════════════

function SortIcon({ field, current, dir }: { field: SortField; current: SortField; dir: SortDir }) {
  if (field !== current) return <span className="w-3" />;
  return dir === "asc" ? <ChevronUp size={10} className="text-[var(--brand)]" /> : <ChevronDown size={10} className="text-[var(--brand)]" />;
}

// ═══════════════════════════════════════════════════════════════
//  TABLE
// ═══════════════════════════════════════════════════════════════

function TaskTable({
  runs, sortField, sortDir, onSort,
}: {
  runs: SchedulerTaskRun[]; sortField: SortField; sortDir: SortDir; onSort: (f: SortField) => void;
}) {
  const columns: { field: SortField; label: string; className: string }[] = [
    { field: "task_name", label: "任务名称", className: "min-w-[200px]" },
    { field: "task_type", label: "类型", className: "min-w-[120px]" },
    { field: "trade_date", label: "交易日", className: "min-w-[90px]" },
    { field: "status", label: "状态", className: "min-w-[80px]" },
    { field: "started_at", label: "开始时间", className: "min-w-[140px]" },
    { field: "step_count", label: "步骤", className: "min-w-[50px] text-right" },
  ];

  if (!runs.length) return <FAEmptyState title="无匹配任务" description="调整筛选条件重试" className="py-12" />;

  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full text-left" style={{ borderCollapse: "collapse" }}>
        {/* Header */}
        <thead className="sticky top-0 z-10" style={{ background: "var(--bg-panel)" }}>
          <tr className="border-b-2 border-[var(--border)]">
            {columns.map(col => (
              <th
                key={col.field}
                onClick={() => onSort(col.field)}
                className={`px-3 py-2 text-[8px] font-semibold text-[var(--fg-5)] uppercase tracking-wider cursor-pointer hover:text-[var(--fg-3)] select-none ${col.className}`}
              >
                <div className="flex items-center gap-1">
                  {col.label}
                  <SortIcon field={col.field} current={sortField} dir={sortDir} />
                </div>
              </th>
            ))}
            <th className="w-[40px] px-2 py-2" />
          </tr>
        </thead>

        {/* Body */}
        <tbody>
          {runs.map((run, idx) => {
            const tone = getStatusTone(run.status);
            const color = CATEGORY_COLORS[run.category] ?? "#94a3b8";
            const time = formatTime(run.started_at);
            const isEven = idx % 2 === 0;

            return (
              <tr
                key={run.run_id}
                className="border-b border-[var(--border-faint)] hover:bg-[var(--bg-card-inner)] transition-colors"
                style={{ background: isEven ? "var(--bg-card)" : "var(--bg-panel)" }}
              >
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="w-0.5 h-4 rounded-full shrink-0" style={{ background: color }} />
                    <div>
                      <div className="text-[9px] font-medium text-[var(--fg-2)] truncate max-w-[200px]">{run.task_name}</div>
                      <div className="text-[7px] font-mono text-[var(--fg-6)]">{run.run_id.slice(0, 8)}</div>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2">
                  <span className="rounded px-1.5 py-px text-[8px] font-semibold" style={{ background: `${color}18`, color }}>
                    {CATEGORY_LABELS[run.category] ?? run.category}
                  </span>
                  <div className="text-[7px] font-mono text-[var(--fg-6)] mt-0.5">{run.task_type}</div>
                </td>
                <td className="px-3 py-2">
                  <span className="text-[9px] font-mono text-[var(--fg-3)]">{run.trade_date || "—"}</span>
                </td>
                <td className="px-3 py-2">
                  <FAStatusPill tone={tone}>{formatStatus(run.status)}</FAStatusPill>
                </td>
                <td className="px-3 py-2">
                  <div className="text-[8px] font-mono text-[var(--fg-4)]">{time}</div>
                  {run.ended_at && (
                    <div className="text-[7px] text-[var(--fg-6)] mt-0.5">
                      {((new Date(run.ended_at).getTime() - new Date(run.started_at!).getTime()) / 1000).toFixed(1)}s
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  <span className="text-[9px] font-mono text-[var(--fg-3)]">{run.step_count || 0}</span>
                </td>
                <td className="px-2 py-2">
                  <Link
                    to={`/agent-tasks/${run.run_id}`}
                    className="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-[var(--bg-hover)] text-[var(--fg-5)] hover:text-[var(--brand)] transition-colors"
                    title="查看详情"
                  >
                    <ExternalLink size={12} />
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  PAGE
// ═══════════════════════════════════════════════════════════════

export function TaskScheduleListPage() {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortField, setSortField] = useState<SortField>("started_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const { data, isLoading, isError, error, refresh } = useSchedulerOverview(30);

  function handleSort(field: SortField) {
    if (sortField === field) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  const filteredRuns = useMemo(() => {
    if (!data) return [];
    let runs = [...data.task_runs];

    // Search
    if (query.trim()) {
      const q = query.toLowerCase();
      runs = runs.filter(r =>
        r.task_name.toLowerCase().includes(q) ||
        r.task_type.toLowerCase().includes(q) ||
        (r.trade_date || "").includes(q)
      );
    }

    // Status filter
    if (statusFilter !== "all") {
      runs = runs.filter(r => {
        const s = r.status.toLowerCase();
        if (statusFilter === "failed") return s === "failed" || s === "blocked" || s === "stale";
        return s === statusFilter;
      });
    }

    // Sort
    runs.sort((a, b) => {
      const va = a[sortField];
      const vb = b[sortField];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      const cmp = String(va).localeCompare(String(vb), undefined, { numeric: true });
      return sortDir === "asc" ? cmp : -cmp;
    });

    return runs;
  }, [data, query, statusFilter, sortField, sortDir]);

  if (isLoading)
    return <PageShell><div className="flex justify-center py-20"><RefreshCw size={20} className="animate-spin text-[var(--fg-5)]" /></div></PageShell>;
  if (isError)
    return <PageShell><div className="flex flex-col items-center py-20"><XCircle size={28} className="text-[var(--down)] mb-2" /><span className="text-sm text-[var(--fg-3)]">{error?.message ?? "加载失败"}</span><button onClick={refresh} className="mt-2 rounded border px-3 py-1 text-xs">重试</button></div></PageShell>;
  if (!data) return null;

  const stats = {
    total: data.summary.total_runs,
    success: data.summary.success_count,
    failed: data.summary.failed_count,
    running: data.summary.running_count,
  };

  return (
    <PageShell>
      <ListHeader
        query={query} setQuery={setQuery}
        statusFilter={statusFilter} setStatusFilter={setStatusFilter}
        sortField={sortField} sortDir={sortDir} onSort={handleSort}
        onRefresh={refresh}
      />

      {/* Stats bar */}
      <div className="flex items-center gap-4 px-3 py-1.5 text-[8px] border-b border-[var(--border-faint)]" style={{ background: "var(--bg-panel)" }}>
        <span className="text-[var(--fg-5)]">
          共 <span className="font-semibold text-[var(--fg-2)]">{stats.total}</span> 条
        </span>
        <span className="flex items-center gap-1">
          <CheckCircle size={9} className="text-[var(--up)]" />
          <span className="text-[var(--up)] font-semibold">{stats.success}</span>
        </span>
        <span className="flex items-center gap-1">
          <XCircle size={9} className={stats.failed > 0 ? "text-[var(--down)]" : "text-[var(--fg-5)]"} />
          <span className={stats.failed > 0 ? "text-[var(--down)] font-semibold" : "text-[var(--fg-5)]"}>{stats.failed}</span>
        </span>
        {stats.running > 0 && (
          <span className="flex items-center gap-1">
            <RefreshCw size={9} className="text-[var(--warn)] animate-spin" />
            <span className="text-[var(--warn)] font-semibold">{stats.running}</span>
          </span>
        )}
        <span className="ml-auto text-[var(--fg-6)]">{filteredRuns.length} 条匹配</span>
      </div>

      <TaskTable runs={filteredRuns} sortField={sortField} sortDir={sortDir} onSort={handleSort} />
    </PageShell>
  );
}

function PageShell({ children }: { children: React.ReactNode }) {
  return <div className="finance-page-shell flex flex-col h-full">{children}</div>;
}

export default TaskScheduleListPage;
