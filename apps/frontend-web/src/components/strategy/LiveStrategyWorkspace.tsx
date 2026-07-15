import { Activity, AlertTriangle, Database, Gauge, Target } from "lucide-react";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { LiveStrategyScenarios } from "@/components/strategy/LiveStrategyScenarios";
import type { LiveStrategyResponse, LiveStrategyStatus } from "@/types/live-strategy";

interface LiveStrategyWorkspaceProps {
  data: LiveStrategyResponse | null;
  isLoading: boolean;
  error: Error | null;
}

const feasibilityFields = [
  ["data_ready", "数据就绪"],
  ["level_ready", "关键位就绪"],
  ["trigger_ready", "触发条件"],
  ["risk_ready", "风险参数"],
  ["rr_ready", "风险收益比"],
  ["execution_ready", "执行条件"],
] as const;

function formatNumber(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatPercent(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${value.toFixed(2)}%`;
}

function formatTimestamp(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function liveStatusTone(status: LiveStrategyStatus): FAStatusTone {
  if (status === "SUSPENDED_DATA") return "down";
  if (status === "TRIGGERED") return "up";
  if (status === "ARMED") return "warn";
  if (status === "WATCHING") return "info";
  return "neutral";
}

function availabilityTone(status: LiveStrategyResponse["status"]): FAStatusTone {
  if (status === "available") return "up";
  if (status === "partial") return "warn";
  return "down";
}

function reasonFor(data: LiveStrategyResponse, key: string, ready: boolean) {
  if (ready) return "后端已确认";
  const reasons = data.feasibility.reasons[key] ?? [];
  return reasons.length > 0 ? reasons.join("；") : "后端未返回该项不可用原因";
}

function LiveStrategyUnavailable({ isLoading, error }: Pick<LiveStrategyWorkspaceProps, "isLoading" | "error">) {
  return (
    <section className="live-strategy-unavailable" aria-live="polite">
      <AlertTriangle size={16} aria-hidden="true" />
      <div>
        <strong>实时策略{isLoading ? "加载中" : "不可用"}</strong>
        <p>{isLoading ? "正在读取 /api/live-strategy/latest；下方每日 StrategyCard 保持可用。" : error?.message ?? "后端未返回 live_strategy.v1；下方每日 StrategyCard 保持可用。"}</p>
      </div>
    </section>
  );
}

function MarketStrip({ data }: { data: LiveStrategyResponse }) {
  const timestamps = Object.entries(data.live_market.timestamps);
  return (
    <section className="live-strategy-market-strip" aria-label="实时行情">
      <div className="live-strategy-market-price">
        <span>Canonical 5m close</span>
        <strong className="fa-price-num">{formatNumber(data.live_market.price)}</strong>
        <small>{data.asset}</small>
      </div>
      <div className="live-strategy-market-details">
        <span>Bid / Ask <b className="fa-num">{formatNumber(data.live_market.bid)} / {formatNumber(data.live_market.ask)}</b></span>
        <span>变动 <b className="fa-num">{formatPercent(data.live_market.change_pct)}</b></span>
        <span>来源 <b>{data.live_market.provider ?? "—"}</b></span>
        <span>新鲜度 <b className="fa-num">{data.live_market.freshness_seconds === null ? "—" : `${formatNumber(data.live_market.freshness_seconds, 0)}s`}</b></span>
        <span>时段 <b>{data.live_market.session ?? "—"}</b></span>
        <span>行情状态 <b>{data.live_market.status ?? "—"}</b></span>
      </div>
      <div className="live-strategy-timestamps">
        {timestamps.length > 0
          ? timestamps.map(([label, value]) => <span key={label}>{label}: <b className="fa-num">{formatTimestamp(value)}</b></span>)
          : <span>时间戳：后端未提供</span>}
      </div>
    </section>
  );
}

function StrategyStatusCard({ data }: { data: LiveStrategyResponse }) {
  const relatedLevel = data.update_reason.related_level;
  return (
    <article className="live-strategy-panel">
      <div className="live-strategy-panel-heading">
        <div><Target size={15} aria-hidden="true" /><h2>实时策略状态</h2></div>
        <FAStatusPill tone={liveStatusTone(data.strategy_status)}>{data.strategy_status}</FAStatusPill>
      </div>
      <div className="live-strategy-status-grid">
        <div><span>Baseline ID</span><code>{data.baseline_strategy_id ?? data.baseline.strategy_card_id ?? "—"}</code></div>
        <div><span>Live ID / 版本</span><code>{data.strategy_id ?? "—"}</code><b>{data.strategy_version ?? data.baseline.version ?? "—"}</b></div>
        <div><span>方向 / Regime</span><b>{data.baseline.bias ?? "—"} / {data.baseline.market_regime ?? "—"}</b></div>
        <div><span>置信度</span><b className="fa-num">{formatNumber(data.baseline.confidence)}</b></div>
      </div>
      <div className="live-strategy-reason">
        <span>原因代码</span><strong>{data.update_reason.reason_code ?? "—"}</strong>
        {relatedLevel ? <b>关联位：{relatedLevel.role ?? "—"} {formatNumber(relatedLevel.value)}</b> : null}
        <p>{data.update_reason.message ?? "后端未提供状态说明。"}</p>
      </div>
      <PriceEventStatus data={data} />
    </article>
  );
}

function PriceEventStatus({ data }: { data: LiveStrategyResponse }) {
  const event = data.market_state.latest_price_event;
  const confirmation15m = data.market_state.confirmation_15m;
  return (
    <div className="live-strategy-price-event" aria-label="后端价格事件确认">
      <div><Activity size={14} aria-hidden="true" /><span>Latest price event</span><strong>{event?.event_type ?? "—"}</strong></div>
      <div><span>方向 / 已确认</span><b>{event?.direction ?? "—"} / {event ? (event.confirmed ? "confirmed" : "unconfirmed") : "—"}</b></div>
      <div><span>事件价格 / 时间</span><b className="fa-num">{formatNumber(event?.price)} / {formatTimestamp(event?.detected_at)}</b></div>
      <div><span>5m confirmation</span><b className="fa-num">{event?.confirmation.five_minute_closes.map((value) => formatNumber(value)).join(" / ") || "—"}</b></div>
      <div><span>15m confirmation</span><b className="fa-num">{confirmation15m ? `${confirmation15m.confirmed ? "confirmed" : "unconfirmed"} / ${formatNumber(confirmation15m.close)}` : formatNumber(event?.confirmation.fifteen_minute_close)}</b></div>
    </div>
  );
}

function NearestLevelCard({ data }: { data: LiveStrategyResponse }) {
  const level = data.market_state.nearest_level;
  return (
    <article className="live-strategy-panel">
      <div className="live-strategy-panel-heading">
        <div><Gauge size={15} aria-hidden="true" /><h2>最近关键位</h2></div>
        <FAStatusPill tone="info">{data.market_state.gamma_regime ?? "Gamma 未提供"}</FAStatusPill>
      </div>
      <div className="live-strategy-level-grid">
        <div><span>角色 / 点位</span><strong>{level?.role ?? "—"} <b className="fa-num">{formatNumber(level?.value ?? null)}</b></strong></div>
        <div><span>距离 / 距离%</span><strong className="fa-num">{formatNumber(level?.distance ?? null)} / {formatPercent(level?.distance_pct ?? null)}</strong></div>
        <div><span>关键位事件</span><strong>{data.market_state.level_event ?? "—"}</strong></div>
        <div><span>ATR14</span><strong className="fa-num">{formatNumber(data.market_state.atr14)}</strong></div>
      </div>
    </article>
  );
}

function FeasibilityCard({ data }: { data: LiveStrategyResponse }) {
  return (
    <article className="live-strategy-panel live-strategy-panel--feasibility">
      <div className="live-strategy-panel-heading">
        <div><Database size={15} aria-hidden="true" /><h2>可行性</h2></div>
        <FAStatusPill tone={availabilityTone(data.status)}>{data.status}</FAStatusPill>
      </div>
      <div className="live-strategy-feasibility-grid">
        {feasibilityFields.map(([key, label]) => {
          const ready = data.feasibility[key];
          return (
            <div className="live-strategy-feasibility-item" key={key}>
              <FAStatusPill tone={ready ? "up" : "dim"} dot={false}>{ready ? "就绪" : "未就绪"}</FAStatusPill>
              <strong>{label}</strong>
              <p>{reasonFor(data, key, ready)}</p>
            </div>
          );
        })}
      </div>
    </article>
  );
}

export function LiveStrategyWorkspace({ data, isLoading, error }: LiveStrategyWorkspaceProps) {
  if (!data) return <LiveStrategyUnavailable isLoading={isLoading} error={error} />;

  return (
    <section className="live-strategy-workspace" aria-label="XAUUSD 实时策略">
      <div className="live-strategy-workspace-heading">
        <div>
          <span className="fa-eyebrow">live_strategy.v1</span>
          <h1>实时策略工作区</h1>
          <p>只读消费后端实时策略；不在前端计算 ATR、状态、关键位或交易参数。</p>
        </div>
        <span className="fa-num">更新于 {formatTimestamp(data.updated_at)}</span>
      </div>
      <MarketStrip data={data} />
      <div className="live-strategy-workspace-grid">
        <StrategyStatusCard data={data} />
        <NearestLevelCard data={data} />
      </div>
      <FeasibilityCard data={data} />
      <LiveStrategyScenarios
        activeScenario={data.active_scenario}
        setups={data.setups}
        noTrade={data.no_trade}
        dataBlocked={data.strategy_status === "SUSPENDED_DATA" || data.status !== "available"}
      />
      {data.data_quality.warnings.length > 0 ? (
        <div className="live-strategy-quality" role="note">
          <AlertTriangle size={15} aria-hidden="true" />
          <span>{data.data_quality.warnings.join("；")}</span>
        </div>
      ) : null}
    </section>
  );
}
