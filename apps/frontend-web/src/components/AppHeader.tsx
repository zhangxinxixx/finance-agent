import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { RefreshCw, Clock, Moon, Sun } from "lucide-react";
import { useDataStatus } from "../hooks/useDataStatus";
import { HeaderBreadcrumb } from "./shared/HeaderBreadcrumb";
import { ReportUpdateNotifications } from "./ReportUpdateNotifications";

const viewLabels: Record<string, string> = {
  "/dashboard/analysis": "综合分析",
  "/dashboard": "黄金宏观交易驾驶舱",
  "/gold-mainlines": "黄金主线归因",
  "/rates-dollar": "利率与美元",
  "/oil-geopolitics": "石油与地缘",
  "/data-ingestion": "数据接入",
  "/event-flow": "事件流",
  "/event-flow/": "事件详情",
  "/feishu-monitor": "飞书监控",
  "/market-monitor": "市场监控",
  "/cme-options": "期权结构",
  "/reports": "报告中心",
  "/reports/": "报告详情",
  "/knowledge-base": "知识库",
  "/knowledge": "知识库",
  "/agent-tasks": "智能体任务",
  "/agent-tasks/": "任务详情",
  "/scheduler": "调度中心",
  "/scheduler/grid": "任务网格",
  "/scheduler/tasks": "任务计划",
  "/review-center": "人工复核",
  "/strategy": "每日策略框架",
  "/settings": "系统设置",
  "/settings/audit": "审计日志",
  "/settings/llm-audit": "LLM 调用审计",
};

function getViewLabel(pathname: string): string {
  const match = Object.entries(viewLabels)
    .sort((left, right) => right[0].length - left[0].length)
    .find(([prefix]) => pathname === prefix || pathname.startsWith(prefix));
  return match?.[1] || pathname;
}

function formatLocalClock(value: Date): { date: string; time: string } {
  return {
    date: value.toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }),
    time: value.toLocaleTimeString("zh-CN", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }),
  };
}

interface AppHeaderProps {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  headerContent?: ReactNode | null;
}

export function AppHeader({ theme, onToggleTheme, headerContent }: AppHeaderProps) {
  const location = useLocation();
  const label = getViewLabel(location.pathname);
  const [now, setNow] = useState(() => new Date());
  const { date: dateStr, time: timeStr } = useMemo(() => formatLocalClock(now), [now]);
  const { refetch } = useDataStatus();

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <header className="header">
      <div className="header-primary">
        {headerContent ?? (
          <HeaderBreadcrumb title={label} />
        )}
      </div>

      <div className="header-right">
        <div className="hidden items-center gap-1.5 text-[11px] text-finance-text-muted 2xl:flex">
          <Clock size={11} />
          <span>{dateStr}</span>
          <span className="text-finance-text-tertiary">|</span>
          <span className="text-finance-accent-soft">{timeStr} 本地</span>
        </div>

        <button className="rounded-full border border-transparent p-2.5 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-hover)]" title="刷新" onClick={() => refetch()}>
          <RefreshCw size={14} className="text-finance-text-muted" />
        </button>
        <button
          className="rounded-full border border-transparent p-2.5 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-hover)]"
          title={theme === "dark" ? "切换亮色" : "切换夜间"}
          onClick={onToggleTheme}
        >
          {theme === "dark" ? (
            <Sun size={14} className="text-finance-text-muted" />
          ) : (
            <Moon size={14} className="text-finance-text-muted" />
          )}
        </button>
        <ReportUpdateNotifications />

        <div className="flex items-center gap-2 rounded-full border border-transparent px-2 py-1.5 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-hover)]">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold text-white"
            style={{ background: "var(--brand-gradient)" }}
          >
            T
          </div>
          <span className="hidden text-[12px] text-finance-text-secondary md:block">研究员</span>
        </div>
      </div>
    </header>
  );
}
