import { useLocation } from "react-router-dom";
import { ContextPanelShell } from "./shared/ContextPanel";
import { FACard } from "./shared/FACard";
import { FAStatusPill } from "./shared/FAStatusPill";

const contextByPath: Record<
  string,
  {
    title: string;
    eyebrow: string;
    accent: "brand" | "up" | "down" | "warn" | "info" | "none";
    summary: string;
    metrics: { label: string; value: string }[];
  }
> = {
  "/dashboard": {
    title: "Daily Focus",
    eyebrow: "Dashboard Context",
    accent: "brand",
    summary: "汇总市场状态、最新输出、风险告警与任务运行，作为盘前主工作台入口。",
    metrics: [
      { label: "headline", value: "market overview" },
      { label: "outputs", value: "latest reports" },
      { label: "risk", value: "alerts / warnings" },
      { label: "trace", value: "source refs" },
    ],
  },
  "/market-monitor": {
    title: "Signal Stack",
    eyebrow: "Market Context",
    accent: "info",
    summary: "关注黄金、美元、实际利率、流动性与跨资产联动，页面以监控密度为先。",
    metrics: [
      { label: "xauusd", value: "watch" },
      { label: "dxy", value: "watch" },
      { label: "real_10y", value: "watch" },
      { label: "liquidity", value: "watch" },
    ],
  },
  "/cme-options": {
    title: "Structure Focus",
    eyebrow: "CME Context",
    accent: "warn",
    summary: "围绕墙位、Gamma Zero、关键位与数据层级组织，只读展示结构状态。",
    metrics: [
      { label: "gamma zero", value: "tracked" },
      { label: "call wall", value: "tracked" },
      { label: "put wall", value: "tracked" },
      { label: "status", value: "FINAL / PRELIM" },
    ],
  },
  "/reports": {
    title: "Research Output",
    eyebrow: "Reports Context",
    accent: "info",
    summary: "报告页侧重阅读、产物引用、来源链路与报告族切换，不承载行情判断逻辑。",
    metrics: [
      { label: "family", value: "report set" },
      { label: "artifact", value: "read only" },
      { label: "trace", value: "linked" },
      { label: "date/run", value: "selected" },
    ],
  },
  "/agent-tasks": {
    title: "Pipeline Runtime",
    eyebrow: "Ops Context",
    accent: "info",
    summary: "任务运行页侧重 step timeline、runtime log、review queue 与产物引用。",
    metrics: [
      { label: "runs", value: "queued / running" },
      { label: "steps", value: "timeline" },
      { label: "logs", value: "terminal" },
      { label: "review", value: "pending" },
    ],
  },
  "/data-ingestion": {
    title: "Source Health",
    eyebrow: "Ingestion Context",
    accent: "warn",
    summary: "数据接入页用于观察 source health、missing sources、pipeline layer 与 freshness。",
    metrics: [
      { label: "sources", value: "configured" },
      { label: "missing", value: "tracked" },
      { label: "layers", value: "pipeline" },
      { label: "snapshot", value: "latest" },
    ],
  },
};

const CONTEXT_BOX_CLASS_NAME = "rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2.5";

export function ContextRightPanel() {
  const location = useLocation();
  const context = Object.entries(contextByPath)
    .sort((left, right) => right[0].length - left[0].length)
    .find(([prefix]) => location.pathname === prefix || location.pathname.startsWith(prefix))?.[1] ?? {
    title: "Context Snapshot",
    eyebrow: "Workstation Context",
    accent: "none" as const,
    summary: "当前页面尚未定义专用右栏，上下文面板保留统一外壳与追溯语义。",
    metrics: [
      { label: "context", value: "pending" },
      { label: "trace", value: "available" },
      { label: "status", value: "read only" },
      { label: "layout", value: "workstation" },
    ],
  };

  return (
    <ContextPanelShell
      className="hidden flex-col xl:flex"
      width="var(--rightpanel-w)"
      padded={false}
      style={{
        gap: 12,
        border: "none",
        borderLeft: "1px solid var(--border)",
        borderRadius: 0,
        background:
          "linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0)), var(--bg-panel)",
        padding: "14px 12px",
      }}
    >
      <FACard
        title={context.title}
        eyebrow={context.eyebrow}
        accent={context.accent}
        action={<FAStatusPill tone="dim">read only</FAStatusPill>}
        bodyClassName="space-y-2"
      >
        <div className={`${CONTEXT_BOX_CLASS_NAME} text-[10px] leading-5 text-finance-text-muted`}>
          {context.summary}
        </div>
        {context.metrics.map((r) => (
          <div key={r.label} className={`${CONTEXT_BOX_CLASS_NAME} flex items-center justify-between`}>
            <div className="flex min-w-0 items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-finance-bullish" />
              <span className="truncate text-[10px] text-finance-text-tertiary">{r.label}</span>
            </div>
            <span className="font-mono text-[10px] font-semibold text-finance-text-secondary">{r.value}</span>
          </div>
        ))}
      </FACard>

      <FACard title="Market Bias" eyebrow="Scenario Stack" accent="info" bodyClassName="space-y-2.5">
        <div className={`${CONTEXT_BOX_CLASS_NAME} text-[10px] leading-5 text-finance-text-muted`}>
          等待分析数据。运行盘前流水线后生成策略输出。
        </div>
        <div className="grid gap-2">
          {[
            { label: "XAUUSD", value: "—" },
            { label: "DXY", value: "—" },
            { label: "10Y Real", value: "—" },
            { label: "T10YIE", value: "—" },
            { label: "ON RRP", value: "—" },
            { label: "TGA", value: "—" },
          ].map((item) => (
            <div key={item.label} className="flex items-center justify-between rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-terminal)] px-3 py-2">
              <span className="text-[10px] text-[var(--fg-5)]">{item.label}</span>
              <span className="fa-num text-[11px] text-[var(--fg-2)]">{item.value}</span>
            </div>
          ))}
        </div>
      </FACard>

      <FACard title="Source Trace" eyebrow="Context Rail" accent="brand">
        <div className={`${CONTEXT_BOX_CLASS_NAME} text-[10px] text-finance-text-muted`}>
          <p>尚未加载数据源。</p>
          <p className="mt-1 text-finance-text-tertiary">raw → parsed → features → analysis → output</p>
        </div>
      </FACard>

      <FACard title="Runtime Info" eyebrow="System Runtime" accent="none">
        <div className={`${CONTEXT_BOX_CLASS_NAME} space-y-2 text-[10px]`}>
          <div className="flex justify-between gap-3">
            <span className="text-finance-text-muted">状态</span>
            <span className="text-finance-text-tertiary">空闲</span>
          </div>
          <div className="flex justify-between gap-3">
            <span className="text-finance-text-muted">引擎</span>
            <span className="truncate text-finance-purple">finance-agent/0.3</span>
          </div>
        </div>
      </FACard>
    </ContextPanelShell>
  );
}
