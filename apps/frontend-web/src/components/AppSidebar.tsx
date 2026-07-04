import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  DatabaseZap,
  Activity,
  Calendar,
  LineChart,
  Gauge,
  BarChart3,
  FileText,
  MessagesSquare,
  BookOpen,
  Bot,
  Flame,
  Target,
  Settings,
  GitBranch,
  ShieldCheck,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import { getLatestTradeDate, isWeekend } from "@/lib/date";

const navItems = [
  { id: "dashboard", zh: "总览", icon: LayoutDashboard, path: "/dashboard" },
  { id: "gold-mainlines", zh: "黄金主线", icon: Target, path: "/gold-mainlines" },
  { id: "rates-dollar", zh: "利率与美元", icon: Gauge, path: "/rates-dollar" },
  { id: "oil-geopolitics", zh: "石油与地缘", icon: Flame, path: "/oil-geopolitics" },
  { id: "data-ingestion", zh: "数据接入", icon: DatabaseZap, path: "/data-ingestion" },
  { id: "event-flow", zh: "事件流", icon: GitBranch, path: "/event-flow" },
  { id: "feishu-monitor", zh: "飞书监控", icon: MessagesSquare, path: "/feishu-monitor" },
  { id: "market-monitor", zh: "市场监控", icon: LineChart, path: "/market-monitor" },
  { id: "cme-options", zh: "期权结构", icon: BarChart3, path: "/cme-options" },
  { id: "reports", zh: "报告中心", icon: FileText, path: "/reports" },
  { id: "knowledge-base", zh: "知识库", icon: BookOpen, path: "/knowledge-base" },
  { id: "scheduler", zh: "调度中心", icon: Bot, path: "/scheduler" },
  { id: "review-center", zh: "人工复核", icon: ShieldCheck, path: "/review-center" },
  { id: "strategy", zh: "每日策略", icon: Target, path: "/strategy" },
  { id: "settings", zh: "系统设置", icon: Settings, path: "/settings" },
];

interface AppSidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function AppSidebar({ collapsed, onToggleCollapsed }: AppSidebarProps) {
  const showWeekendMode = isWeekend();
  const latestTradeDate = getLatestTradeDate();
  const compactTradeDate = latestTradeDate.slice(5);
  const ToggleIcon = collapsed ? ChevronsRight : ChevronsLeft;

  return (
    <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`}>
      <div className="sidebar-logo">
        <div className="sidebar-logo-mark">
          <Activity size={16} />
        </div>
        <div className="sidebar-logo-copy">
          <div className="sidebar-logo-text-zh">金融分析中台</div>
          {showWeekendMode ? (
            <div
              className="sidebar-market-mode"
              title={`周末模式 — 市场数据展示最近交易日（${latestTradeDate}），新闻事件实时更新`}
            >
              <Calendar size={10} className="sidebar-market-mode-icon" />
              <span className="sidebar-market-mode-text">周末 · {compactTradeDate} · 新闻实时</span>
            </div>
          ) : (
            <div className="text-[10px] tracking-[0.06em] text-[var(--fg-5)]">研究工作台</div>
          )}
        </div>
        <button
          type="button"
          className="sidebar-collapse-button"
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          title={collapsed ? "展开侧边栏" : "收起侧边栏"}
          onClick={onToggleCollapsed}
        >
          <ToggleIcon />
        </button>
      </div>

      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.id}
              to={item.path}
              title={item.zh}
              className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
            >
              <Icon className="icon" />
              <div className="nav-item-label">
                <div className="truncate text-[12px]">{item.zh}</div>
              </div>
            </NavLink>
          );
        })}
      </nav>

      <div className="sidebar-bottom">
        <div className="sidebar-bottom-row">
          <span className="sidebar-bottom-title">本地终端</span>
          <span className="sidebar-bottom-status">
            <span className="sidebar-bottom-dot" />
            <span className="sidebar-bottom-status-text">在线</span>
          </span>
        </div>
        <div className="sidebar-bottom-note">当前会话已连接</div>
      </div>
    </aside>
  );
}
