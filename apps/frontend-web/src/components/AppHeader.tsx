import { useLocation } from "react-router-dom";
import { Search, Bell, RefreshCw, Clock } from "lucide-react";
import { useDataStatus } from "../hooks/useDataStatus";

const viewLabels: Record<string, string> = {
  "/dashboard": "总览",
  "/data-ingestion": "数据接入",
  "/event-flow": "事件流",
  "/market-monitor": "市场监控",
  "/cme-options": "CME 期权结构",
  "/reports": "报告中心",
  "/reports/": "报告详情",
  "/knowledge-base": "知识库",
  "/agent-tasks": "智能体任务",
  "/agent-tasks/": "任务详情",
  "/settings": "系统设置",
};

function getViewLabel(pathname: string): string {
  const match = Object.entries(viewLabels)
    .sort((left, right) => right[0].length - left[0].length)
    .find(([prefix]) => pathname === prefix || pathname.startsWith(prefix));
  return match?.[1] || pathname;
}

export function AppHeader() {
  const location = useLocation();
  const label = getViewLabel(location.pathname);
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10);
  const timeStr = now.toTimeString().slice(0, 8);
  const { refetch } = useDataStatus();

  return (
    <header className="header">
      <div className="min-w-0">
        <div className="header-breadcrumb">
          <span className="text-[9px] tracking-[0.08em] text-finance-text-muted">金融分析中台</span>
          <span className="text-[10px] text-finance-text-tertiary">/</span>
          <span className="truncate text-[11px] font-semibold text-finance-text-primary">{label}</span>
        </div>
      </div>

      <div className="flex min-w-0 flex-1 items-center justify-center px-5">
        <div className="header-search">
          <Search size={11} className="text-finance-text-muted" />
          <input
            type="text"
            placeholder="搜索市场、事件、报告..."
            className="w-full bg-transparent text-[10px] text-finance-text-secondary outline-none placeholder:text-finance-text-muted"
          />
        </div>
      </div>

      <div className="header-right">
        <div className="hidden items-center gap-1.5 text-[10px] text-finance-text-muted 2xl:flex">
          <Clock size={10} />
          <span>{dateStr}</span>
          <span className="text-finance-text-tertiary">|</span>
          <span className="text-finance-accent-soft">{timeStr} UTC</span>
        </div>

        <button className="rounded-full border border-transparent p-2 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-hover)]" title="刷新" onClick={() => refetch()}>
          <RefreshCw size={13} className="text-finance-text-muted" />
        </button>
        <button className="relative rounded-full border border-transparent p-2 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-hover)]" title="告警">
          <Bell size={13} className="text-finance-text-muted" />
          <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-finance-bearish" />
        </button>

        <div className="hidden items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 py-1 text-[9px] font-medium text-[var(--fg-4)] xl:flex">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--brand)]" />
          <span>研究工作台</span>
        </div>

        <div className="flex items-center gap-2 rounded-full border border-transparent px-1.5 py-1 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-hover)]">
          <div
            className="flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold text-white"
            style={{ background: "var(--brand-gradient)" }}
          >
            T
          </div>
          <span className="hidden text-[11px] text-finance-text-secondary md:block">研究员</span>
        </div>
      </div>
    </header>
  );
}
