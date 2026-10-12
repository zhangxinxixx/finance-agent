import { useState } from "react";
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
  BookOpen,
  Bot,
  Flame,
  Target,
  Settings,
  GitBranch,
  ShieldCheck,
  Workflow,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import { isWeekend } from "@/lib/date";
import { useDataStatus } from "@/hooks/useDataStatus";

const navGroups = [
  { id: "core", label: "核心工作区", items: [
    { id: "dashboard", zh: "黄金工作台", icon: LayoutDashboard, path: "/dashboard" },
    { id: "strategy", zh: "策略决策", icon: Target, path: "/strategy" },
    { id: "cme-options", zh: "期权结构", icon: BarChart3, path: "/cme-options" },
    { id: "reports", zh: "报告中心", icon: FileText, path: "/reports" },
  ] },
  { id: "research", label: "研究专题", items: [
    { id: "gold-mainlines", zh: "黄金主线", icon: Target, path: "/gold-mainlines" },
    { id: "market-monitor", zh: "市场监控", icon: LineChart, path: "/market-monitor" },
    { id: "rates-dollar", zh: "利率与美元", icon: Gauge, path: "/rates-dollar" },
    { id: "oil-geopolitics", zh: "石油与地缘", icon: Flame, path: "/oil-geopolitics" },
    { id: "event-flow", zh: "事件流", icon: GitBranch, path: "/event-flow" },
    { id: "knowledge-base", zh: "知识库", icon: BookOpen, path: "/knowledge-base" },
  ] },
  { id: "system", label: "系统管理", items: [
    { id: "review-center", zh: "人工复核", icon: ShieldCheck, path: "/review-center" },
    { id: "data-ingestion", zh: "数据接入", icon: DatabaseZap, path: "/data-ingestion" },
    { id: "scheduler", zh: "调度中心", icon: Bot, path: "/scheduler" },
    { id: "processing-monitor", zh: "加工监控", icon: Workflow, path: "/processing-monitor" },
    { id: "settings", zh: "系统设置", icon: Settings, path: "/settings" },
  ] },
];

interface AppSidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function AppSidebar({ collapsed, onToggleCollapsed }: AppSidebarProps) {
  const [systemOpen, setSystemOpen] = useState(false);
  const [researchOpen, setResearchOpen] = useState(false);
  const showWeekendMode = isWeekend();
  const { data: dataStatus, isError: dataStatusError, isLoading: dataStatusLoading } = useDataStatus();
  const ToggleIcon = collapsed ? ChevronsRight : ChevronsLeft;

  const pageStatus = dataStatusLoading
    ? { label: "检查中", note: "正在读取数据状态", color: "var(--info)", background: "var(--info-soft)", border: "var(--info-border)" }
    : dataStatusError || dataStatus.overall_status === "UNAVAILABLE"
      ? { label: "状态未知", note: "数据状态接口不可用", color: "var(--fg-4)", background: "var(--bg-panel)", border: "var(--border-faint)" }
      : dataStatus.overall_status === "PARTIAL"
        ? { label: "部分可用", note: dataStatus.data_date ? `数据基线 ${dataStatus.data_date}` : "部分数据源已返回", color: "var(--warn)", background: "var(--warn-soft)", border: "var(--warn-border)" }
        : dataStatus.overall_status === "MOCK"
          ? { label: "模拟 / 回退", note: "当前结果不作为实时判断", color: "var(--warn)", background: "var(--warn-soft)", border: "var(--warn-border)" }
          : { label: "数据可用", note: dataStatus.data_date ? `数据基线 ${dataStatus.data_date}` : "已返回数据状态", color: "var(--up)", background: "var(--up-soft)", border: "var(--up-border)" };

  return (
    <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`}>
      <div className="sidebar-logo">
        <div className="sidebar-logo-mark">
          <Activity size={16} />
        </div>
        <div className="sidebar-logo-copy">
          <div className="sidebar-logo-text-zh">黄金研究系统</div>
          {showWeekendMode ? (
            <div
              className="sidebar-market-mode"
              title="周末模式 — 观测日期与新鲜度以各数据源返回和发布节奏为准"
            >
              <Calendar size={10} className="sidebar-market-mode-icon" />
              <span className="sidebar-market-mode-text">周末 · 按源核验日期</span>
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

      <nav className="sidebar-nav" aria-label="主导航">
        {navGroups.map((group) => (
          <section className="sidebar-nav-group" key={group.id} aria-label={group.label}>
            <h2 className="sidebar-nav-group-title fa-label">{group.id === "system" ? <button type="button" aria-expanded={systemOpen} onClick={() => setSystemOpen(!systemOpen)} title="系统管理">{collapsed ? <Settings size={14} /> : `系统管理 ${systemOpen ? "−" : "+"}`}</button>
              : group.id === "research" ? <button type="button" aria-label="更多研究专题" aria-expanded={researchOpen} onClick={() => setResearchOpen(!researchOpen)} title="研究专题">{collapsed ? <LineChart size={14} /> : `更多专题 ${researchOpen ? "−" : "+"}`}</button> : group.label}</h2>
            {(group.id === "system" && !systemOpen || group.id === "research" && !researchOpen ? [] : group.items).map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.id}
                  to={item.path}
                  end={item.id === "settings"}
                  title={item.zh}
                  className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                >
                  <Icon className="icon" />
                  <div className="nav-item-label">
                    <div className="truncate text-[length:var(--type-label)]">{item.zh}</div>
                  </div>
                </NavLink>
              );
            })}
          </section>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <div className="sidebar-bottom-row">
          <span className="sidebar-bottom-title">页面数据</span>
          <span
            className="sidebar-bottom-status"
            style={{
              color: pageStatus.color,
              background: pageStatus.background,
              borderColor: pageStatus.border,
            }}
          >
            <span className="sidebar-bottom-dot" />
            <span className="sidebar-bottom-status-text">{pageStatus.label}</span>
          </span>
        </div>
        <div className="sidebar-bottom-note">{pageStatus.note}</div>
      </div>
    </aside>
  );
}
