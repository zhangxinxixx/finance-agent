import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  DatabaseZap,
  Activity,
  LineChart,
  BarChart3,
  FileText,
  MessagesSquare,
  BookOpen,
  Bot,
  Target,
  Settings,
  GitBranch,
  ShieldCheck,
} from "lucide-react";

const navItems = [
  { id: "dashboard", zh: "总览", icon: LayoutDashboard, path: "/dashboard" },
  { id: "data-ingestion", zh: "数据接入", icon: DatabaseZap, path: "/data-ingestion" },
  { id: "event-flow", zh: "事件流", icon: GitBranch, path: "/event-flow" },
  { id: "feishu-monitor", zh: "飞书监控", icon: MessagesSquare, path: "/feishu-monitor" },
  { id: "market-monitor", zh: "市场监控", icon: LineChart, path: "/market-monitor" },
  { id: "cme-options", zh: "期权结构", icon: BarChart3, path: "/cme-options" },
  { id: "reports", zh: "报告中心", icon: FileText, path: "/reports" },
  { id: "knowledge-base", zh: "知识库", icon: BookOpen, path: "/knowledge-base" },
  { id: "scheduler", zh: "调度中心", icon: Bot, path: "/scheduler" },
  { id: "review-center", zh: "人工复核", icon: ShieldCheck, path: "/review-center" },
  { id: "strategy", zh: "策略中心", icon: Target, path: "/strategy" },
  { id: "settings", zh: "系统设置", icon: Settings, path: "/settings" },
];

export function AppSidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-mark" style={{ background: "linear-gradient(135deg, var(--brand-gold), var(--warn))" }}>
          <Activity size={15} />
        </div>
        <div className="min-w-0">
          <div className="sidebar-logo-text-zh">金融分析中台</div>
          <div className="text-[9px] tracking-[0.06em] text-[var(--fg-5)]">研究工作台</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.id}
              to={item.path}
              className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
            >
              <Icon className="icon" />
              <div className="min-w-0">
                <div className="truncate text-[11px]">{item.zh}</div>
              </div>
            </NavLink>
          );
        })}
      </nav>

      <div className="sidebar-bottom">
        <div className="flex items-center justify-between gap-2 text-[10px]">
          <span className="text-finance-text-muted">本地终端</span>
          <span className="inline-flex items-center gap-1 rounded-full border border-[var(--up-border)] bg-[var(--up-soft)] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--up)]">
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            在线
          </span>
        </div>
        <div className="mt-1 text-[8px] tracking-[0.06em] text-[var(--fg-5)]">当前会话已连接</div>
      </div>
    </aside>
  );
}
