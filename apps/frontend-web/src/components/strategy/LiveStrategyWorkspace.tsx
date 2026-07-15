import {
  Activity,
  AlertTriangle,
  Clock3,
  Database,
  RefreshCw,
  ShieldCheck,
  Target,
} from "lucide-react";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import type { LiveStrategyResponse, LiveStrategySetup, LiveStrategyStatus } from "@/types/live-strategy";

interface LiveStrategyWorkspaceProps {
  data: LiveStrategyResponse | null;
  isLoading: boolean;
  error: Error | null;
  tradeDate: string | null;
  dailyUpdatedAt: string | null | undefined;
  onRefresh: () => void;
}

const feasibilityFields = [
  ["data_ready", "数据就绪"],
  ["level_ready", "关键位就绪"],
  ["trigger_ready", "触发条件"],
  ["risk_ready", "风险参数"],
  ["rr_ready", "风险收益比"],
  ["execution_ready", "执行条件"],
] as const;

const decisionCopy: Record<LiveStrategyStatus, { title: string; action: string }> = {
  SUSPENDED_DATA: { title: "当前不可执行", action: "等待行情和确认数据恢复，不使用旧价格形成新判断。" },
  TRIGGERED: { title: "场景已经触发", action: "核对入场区、失效位和风险收益比，再确认后端 Gate。" },
  ARMED: { title: "条件接近就绪", action: "等待最后的价格事件与周期确认，不提前执行。" },
  WATCHING: { title: "观察关键位", action: "重点跟踪最近关键位的接近、突破或收回事件。" },
  WAITING: { title: "暂无有效触发", action: "保持观望，等待后端给出完整触发与风险参数。" },
};

const reasonLabels: Record<string, string> = {
  canonical_candle_stale: "XAUUSD 5 分钟 K 线已过期",
  quote_cache_stale: "实时报价缓存已过期",
  baseline_options_trade_date_mismatch: "期权基线日期与当前策略不一致",
  fresh_canonical_5m_required: "等待新的 XAUUSD 5 分钟 K 线",
  confirmed_price_event_required: "等待关键位价格事件确认",
  blocked_data: "数据完整性 Gate 未通过",
  canonical_xauusd_5m_unavailable_or_stale: "等待新的 XAUUSD 5 分钟 K 线",
  no_directional_price_event: "等待关键位价格事件确认",
};

const updateMessageLabels: Record<string, string> = {
  canonical_candle_stale: "XAUUSD 5 分钟 K 线缺失、过期或时间戳无效。",
  outside_approach_range: "当前价格距离最近关键位较远，尚未进入确定性观察区间。",
};

function formatNumber(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatPercent(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${value.toFixed(2)}%`;
}

function activityTotal(summary: Record<string, unknown>, key: "pnt_totals" | "block_totals" | "totals") {
  const totals = summary[key];
  if (!totals || typeof totals !== "object") return null;
  const value = (totals as Record<string, unknown>).total;
  return typeof value === "number" ? value : null;
}

function blockCoverageLabel(summary: Record<string, unknown>) {
  const status = summary.block_coverage_status;
  if (status === "observed") return "Block 已观测";
  if (status === "not_verified") return "Block 未核验";
  return "Block 不可用";
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

function readableReason(reason: string) {
  return reasonLabels[reason] ?? reason;
}

function marketStatusLabel(status: string | null) {
  if (status === "stale") return "行情已过期";
  if (status === "available" || status === "live") return "行情可用";
  if (status === "partial") return "行情部分可用";
  return status ?? "状态未知";
}

function liveStatusLabel(status: LiveStrategyStatus) {
  const labels: Record<LiveStrategyStatus, string> = {
    SUSPENDED_DATA: "数据暂停",
    TRIGGERED: "已触发",
    ARMED: "待确认",
    WATCHING: "观察中",
    WAITING: "等待中",
  };
  return labels[status];
}

function availabilityLabel(status: LiveStrategyResponse["status"]) {
  return status === "available" ? "数据可用" : status === "partial" ? "部分可用" : "数据不可用";
}

function strategyLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    bullish: "看多",
    bearish: "看空",
    neutral: "中性",
    trend_tailwind: "趋势顺风",
    magnet_pin: "磁吸位",
  };
  return labels[value ?? ""] ?? value ?? "—";
}

function dedupeReasons(reasons: string[]) {
  const familyFor = (reason: string) => {
    if (["fresh_canonical_5m_required", "canonical_xauusd_5m_unavailable_or_stale"].includes(reason)) return "fresh_5m";
    if (["confirmed_price_event_required", "no_directional_price_event"].includes(reason)) return "price_event";
    return reason;
  };
  const seen = new Set<string>();
  return reasons.filter((reason) => {
    const family = familyFor(reason);
    if (seen.has(family)) return false;
    seen.add(family);
    return true;
  });
}

const keyLevelLabels: Record<string, string> = {
  primary_resistance: "主压力",
  secondary_resistance: "次级压力",
  primary_support: "主支撑",
  secondary_support: "次级支撑",
  magnet_pin: "磁吸位",
  volatility_hub: "波动枢纽",
  gamma_flip: "Gamma 转换带",
  tail_protection: "尾部保护",
};

function recordValue(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : null;
}

function formatLevelValue(level: Record<string, unknown>) {
  const band = recordValue(level.band);
  const lower = numberValue(band?.lower);
  const upper = numberValue(band?.upper);
  if (lower !== null && upper !== null) return `${formatNumber(lower)} – ${formatNumber(upper)}`;
  return formatNumber(numberValue(level.reference_price) ?? numberValue(level.strike));
}

function formatLevelStrength(value: unknown) {
  const numeric = numberValue(value);
  if (numeric !== null) return `强度 ${numeric.toFixed(2)}`;
  return stringValue(value) ? `强度 ${stringValue(value)}` : "强度未提供";
}

function formatSigned(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined) return "—";
  const formatted = formatNumber(Math.abs(value), digits);
  return value > 0 ? `+${formatted}` : value < 0 ? `-${formatted}` : formatted;
}

function optionSideLabel(value: string | null) {
  if (value === "CALL") return "看涨";
  if (value === "PUT") return "看跌";
  if (value === "BALANCED") return "双边";
  return value ?? "—";
}

function cmeScenarioText(value: string) {
  const replacements: Array<[RegExp, string]> = [
    [/primary support remains defended while price rotates toward the Gamma Flip band/gi, "主支撑未失守，价格向 Gamma 转换带回归"],
    [/primary support ([0-9.,]+) breaks with acceptance/gi, "主支撑 $1 被有效跌破"],
    [/price accepts above the Gamma Flip band and confirms on retest/gi, "有效站上 Gamma 转换带并回踩确认"],
    [/subsequent CME trade dates retain or improve Call OI participation/gi, "后续 CME 交易日看涨 OI 参与度保持或增强"],
    [/price falls back below Gamma Flip ([0-9.,]+)/gi, "价格跌回 Gamma 转换位 $1 下方"],
    [/the reclaimed structure cannot hold on retest/gi, "收复后回踩无法守住"],
    [/primary support breaks with price acceptance and the retest fails/gi, "主支撑被有效跌破，且回抽失败"],
    [/Put protection and downside skew strengthen again/gi, "看跌保护与下行 Skew 重新增强"],
    [/broken support ([0-9.,]+) is reclaimed and held/gi, "重新收复并守住已跌破支撑 $1"],
  ];
  return replacements.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), value);
}

function LiveStrategyUnavailable({ isLoading, error }: Pick<LiveStrategyWorkspaceProps, "isLoading" | "error">) {
  return (
    <section className="live-strategy-unavailable" aria-live="polite">
      <AlertTriangle size={16} aria-hidden="true" />
      <div>
        <strong>当前策略{isLoading ? "加载中" : "不可用"}</strong>
        <p>{isLoading ? "正在读取最新策略状态。" : error?.message ?? "后端未返回实时策略；页面不会使用旧数据补造判断。"}</p>
      </div>
    </section>
  );
}

function CompactRiskStrip({ data }: { data: LiveStrategyResponse }) {
  const issues = dedupeReasons(Array.from(new Set([
    ...data.data_quality.warnings,
    ...data.no_trade.reasons,
  ].filter(Boolean)))).slice(0, 3);
  const recovery = dedupeReasons(Array.from(new Set([
    ...data.no_trade.waiting_conditions,
    ...(data.feasibility.reasons.data_ready ?? []),
    ...(data.feasibility.reasons.trigger_ready ?? []),
  ].filter((reason) => reason && !issues.includes(reason))))).slice(0, 2);

  return (
    <section className="live-strategy-risk-strip" aria-label="数据风险与恢复条件">
      <div className="live-strategy-risk-title">
        <AlertTriangle size={16} aria-hidden="true" />
        <div><span>当前风险约束</span><strong>{issues.length > 0 ? issues.map(readableReason).join(" · ") : "后端未提供阻断原因"}</strong></div>
      </div>
      <div className="live-strategy-recovery-list">
        <span>恢复后自动重评</span>
        {(recovery.length > 0 ? recovery : ["等待后端恢复完整数据"]).map((reason) => (
          <b key={reason}><ShieldCheck size={13} aria-hidden="true" />{readableReason(reason)}</b>
        ))}
      </div>
    </section>
  );
}

function KeyLevelMap({ data }: { data: LiveStrategyResponse }) {
  const preferredRoles = ["primary_resistance", "gamma_flip", "primary_support", "tail_protection"];
  const structuralLevels = preferredRoles
    .map((role) => data.market_state.key_levels.find((candidate) => candidate.role === role))
    .filter((level): level is Record<string, unknown> => Boolean(level));
  const nearest = data.market_state.nearest_level;

  return (
    <section className="live-strategy-level-map" aria-label="今日关键价格地图">
      <header className="live-strategy-current-section-heading">
        <div><Target size={15} aria-hidden="true" /><h2>今日关键价格地图</h2></div>
        <span>后端日度结构位 · 非实时触发</span>
      </header>
      <div className="live-strategy-level-map-list">
        {nearest?.value !== null && nearest?.value !== undefined ? (
          <div className="is-nearest">
            <span>最近关键位</span>
            <strong className="fa-price-num">{formatNumber(nearest.value)}</strong>
            <small>{strategyLabel(nearest.role)} · 距离 {formatPercent(nearest.distance_pct)}</small>
          </div>
        ) : null}
        {structuralLevels.map((level) => {
          const role = stringValue(level.role) ?? "unknown";
          return (
            <div key={role}>
              <span>{keyLevelLabels[role] ?? role}</span>
              <strong className="fa-price-num">{formatLevelValue(level)}</strong>
              <small>{formatLevelStrength(level.strength)} · {stringValue(level.expiry_scope) ?? "期限未提供"}</small>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function CmePositioningMap({ data }: { data: LiveStrategyResponse }) {
  const positioning = data.cme_positioning;
  const available = positioning.status !== "unavailable" && positioning.trade_date !== null;
  const pntTotal = activityTotal(positioning.pnt_summary, "pnt_totals") ?? activityTotal(positioning.pnt_summary, "totals");
  const blockTotal = activityTotal(positioning.pnt_summary, "block_totals");
  const changes = [
    ...positioning.largest_increases.slice(0, 4),
    ...positioning.largest_decreases.slice(0, 2),
  ];
  return (
    <section className="live-strategy-cme-positioning" aria-label="CME 大额持仓与增减仓">
      <header className="live-strategy-current-section-heading">
        <div><Database size={15} aria-hidden="true" /><h2>CME 大额持仓与增减仓</h2></div>
        <span className={positioning.aligned_with_baseline === false ? "is-mismatch" : undefined}>
          {available ? `${positioning.trade_date} · ${positioning.source_status ?? "状态未知"}` : "CME 数据不可用"}
          {positioning.aligned_with_baseline === false ? ` · 基线 ${positioning.baseline_trade_date}` : ""}
        </span>
      </header>
      {!available ? (
        <div className="live-strategy-cme-empty">后端未返回可核验的 CME 持仓比较；页面不补造点位。</div>
      ) : (
        <>
          <div className="live-strategy-cme-structure">
            <div>
              <span>结构状态</span>
              <strong>{positioning.structure_summary.label ?? "后端未给出结构判断"}</strong>
              <small>{positioning.structure_summary.summary ?? "等待确定性结构字段。"}</small>
            </div>
            <div>
              <span>机构意图</span>
              <strong>{positioning.intent_summary.wording ?? positioning.intent_summary.type ?? "不可用"}</strong>
              <small>{positioning.structure_summary.trend_launch_watch ? "已进入趋势启动观察，尚未等同趋势确认" : "尚未进入趋势启动观察"}</small>
            </div>
          </div>
          <div className="live-strategy-cme-summary">
            <div><span>总 OI</span><strong className="fa-num">{formatNumber(positioning.total_oi.current, 0)}</strong></div>
            <div><span>单日变化</span><strong className={`fa-num ${(positioning.total_oi.delta ?? 0) >= 0 ? "is-up" : "is-down"}`}>{formatSigned(positioning.total_oi.delta)}</strong></div>
            <div><span>比较基准</span><strong>{positioning.previous_trade_date ?? "不可用"}</strong></div>
            <div><span>日期对齐</span><strong>{positioning.aligned_with_baseline === true ? "已对齐" : positioning.aligned_with_baseline === false ? "滞后 / 待更新" : "未知"}</strong></div>
            <div><span>PNT / Block</span><strong className="fa-num">{formatNumber(pntTotal, 0)} / {formatNumber(blockTotal, 0)}</strong><small>{blockCoverageLabel(positioning.pnt_summary)}</small></div>
          </div>
          <div className="live-strategy-cme-tables">
            <section>
              <h3>{positioning.large_oi_scope === "nearby_6pct" ? "主战区大额 OI（约 ±6%）" : "绝对 OI 最大点位"}</h3>
              <div className="live-strategy-cme-table-head"><span>Strike</span><span>期限 / 方向</span><span>OI</span><span>ΔOI</span></div>
              {positioning.large_oi_levels.slice(0, 6).map((row) => (
                <div className="live-strategy-cme-table-row" key={`${row.expiry}-${row.strike}`}>
                  <strong className="fa-price-num">{formatNumber(row.strike, 0)}</strong>
                  <span>{row.expiry ?? "—"} · {optionSideLabel(row.dominant_side)}</span>
                  <b className="fa-num">{formatNumber(row.total_oi, 0)}</b>
                  <b className={`fa-num ${(row.total_oi_change ?? 0) >= 0 ? "is-up" : "is-down"}`}>{formatSigned(row.total_oi_change)}</b>
                </div>
              ))}
            </section>
            <section>
              <h3>近期最大增减仓</h3>
              <div className="live-strategy-cme-table-head"><span>Strike</span><span>期限 / 类型</span><span>当前 OI</span><span>ΔOI</span></div>
              {changes.map((row, index) => (
                <div className="live-strategy-cme-table-row" key={`${row.expiry}-${row.strike}-${row.option_type}-${index}`}>
                  <strong className="fa-price-num">{formatNumber(row.strike, 0)}</strong>
                  <span>{row.expiry ?? "—"} · {optionSideLabel(row.option_type)}</span>
                  <b className="fa-num">{formatNumber(row.current_oi, 0)}</b>
                  <b className={`fa-num ${(row.delta ?? 0) >= 0 ? "is-up" : "is-down"}`}>{formatSigned(row.delta)}</b>
                </div>
              ))}
            </section>
          </div>
          <div className="live-strategy-cme-paths" aria-label="CME 三路径">
            {positioning.scenario_paths.map((path) => (
              <article key={path.path_id}>
                <div><strong>{path.label}</strong><span>{path.status === "confirmed" ? "已确认" : path.status === "active" ? "活跃" : "观察"}</span></div>
                <p><b>触发</b>{path.triggers.map(cmeScenarioText).join("；") || "—"}</p>
                <p><b>目标</b><em className="fa-num">{path.targets.map((target) => formatNumber(target, 1)).join(" / ") || "—"}</em></p>
                <p><b>失效</b>{path.invalidation.map(cmeScenarioText).join("；") || "—"}</p>
              </article>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function TodayWatchlist({ data, action }: { data: LiveStrategyResponse; action: string }) {
  const waitingConditions = dedupeReasons(data.no_trade.waiting_conditions).slice(0, 2);
  const readiness = [
    ["data_ready", "行情"],
    ["level_ready", "关键位"],
    ["trigger_ready", "触发"],
    ["risk_ready", "风控"],
    ["rr_ready", "收益风险比"],
  ] as const;

  return (
    <section className="live-strategy-watchlist" aria-label="今日观察清单">
      <header className="live-strategy-current-section-heading">
        <div><Activity size={15} aria-hidden="true" /><h2>今日观察清单</h2></div>
        <FAStatusPill tone={liveStatusTone(data.strategy_status)}>{liveStatusLabel(data.strategy_status)}</FAStatusPill>
      </header>
      <div className="live-strategy-watchlist-grid">
        <div><span>基线判断</span><strong>{strategyLabel(data.baseline.bias)} · {strategyLabel(data.baseline.market_regime)}</strong><small>置信度 {formatPercent(data.baseline.confidence === null ? null : data.baseline.confidence * 100)}</small></div>
        <div><span>观望区间</span><strong className="fa-num">{data.no_trade.range ? `${formatNumber(data.no_trade.range[0])} – ${formatNumber(data.no_trade.range[1])}` : "后端未提供"}</strong><small>区间内不提前形成新判断</small></div>
        <div><span>价格事件</span><strong>{data.market_state.level_event ?? "尚未出现方向性关键位事件"}</strong><small>15m 确认：{data.market_state.confirmation_15m?.confirmed ? "已确认" : "未确认"}</small></div>
        <div><span>下一步动作</span><strong>{action}</strong></div>
      </div>
      <div className="live-strategy-readiness-line" aria-label="策略准备度">
        <span>策略准备度</span>
        {readiness.map(([key, label]) => <b className={data.feasibility[key] ? "is-ready" : "is-waiting"} key={key}>{label} {data.feasibility[key] ? "就绪" : "待确认"}</b>)}
      </div>
      <div className="live-strategy-next-confirmation">
        <span>接下来只看</span>
        {(waitingConditions.length > 0 ? waitingConditions : ["等待后端给出确认条件"]).map((reason) => <strong key={reason}>{readableReason(reason)}</strong>)}
      </div>
    </section>
  );
}

function ActiveSetupSummary({ data }: { data: LiveStrategyResponse }) {
  const setup: LiveStrategySetup | undefined = data.setups.find((item) => item.direction === data.active_scenario);
  if (!setup || data.active_scenario === "no_trade") {
    return (
      <section className="live-strategy-active-plan">
        <div><span>当前场景</span><strong>观望 / 未激活</strong></div>
        <div><span>观望区间</span><strong className="fa-num">{data.no_trade.range ? `${formatNumber(data.no_trade.range[0])} – ${formatNumber(data.no_trade.range[1])}` : "—"}</strong></div>
        <p>{readableReason(data.no_trade.waiting_conditions[0] ?? data.no_trade.reasons[0] ?? "等待后端给出可执行场景。")}</p>
      </section>
    );
  }
  const firstTarget = setup.targets.find((target) => target.price !== null && target.price !== undefined);
  return (
    <section className="live-strategy-active-plan">
      <div><span>当前场景</span><strong>{setup.direction === "long" ? "多头" : "空头"} · {setup.status}</strong></div>
      <div><span>入场区</span><strong className="fa-num">{setup.entry_zone ? `${formatNumber(setup.entry_zone[0])} – ${formatNumber(setup.entry_zone[1])}` : "—"}</strong></div>
      <div><span>失效 / 第一目标</span><strong className="fa-num">{formatNumber(setup.invalidation_level)} / {formatNumber(firstTarget?.price)}</strong></div>
      <p>{setup.trigger_conditions[0] ?? "后端未提供触发条件。"}</p>
    </section>
  );
}

function Diagnostics({ data }: { data: LiveStrategyResponse }) {
  const event = data.market_state.latest_price_event;
  const confirmation15m = data.market_state.confirmation_15m;
  const timestamps = Object.entries(data.live_market.timestamps);
  return (
    <div className="live-strategy-diagnostics-body">
      <section>
        <h3><Target size={14} aria-hidden="true" />策略标识</h3>
        <div className="live-strategy-diagnostic-grid">
          <div><span>Baseline ID</span><code>{data.baseline_strategy_id ?? data.baseline.strategy_card_id ?? "—"}</code></div>
          <div><span>Live ID</span><code>{data.strategy_id ?? "—"}</code></div>
          <div><span>规则版本</span><code>{data.strategy_version ?? data.baseline.version ?? "—"}</code></div>
          <div><span>原因代码</span><code>{data.update_reason.reason_code ?? "—"}</code></div>
        </div>
      </section>
      <section>
        <h3><Activity size={14} aria-hidden="true" />价格事件证据</h3>
        <div className="live-strategy-diagnostic-grid">
          <div><span>事件价格 / 时间</span><b className="fa-num">{formatNumber(event?.price)} / {formatTimestamp(event?.detected_at)}</b></div>
          <div><span>5m closes</span><b className="fa-num">{event?.confirmation.five_minute_closes.map((value) => formatNumber(value)).join(" / ") || "—"}</b></div>
          <div><span>15m close</span><b className="fa-num">{formatNumber(confirmation15m?.close ?? event?.confirmation.fifteen_minute_close)}</b></div>
          <div><span>关键位事件</span><b>{data.market_state.level_event ?? "—"}</b></div>
        </div>
      </section>
      <section className="live-strategy-diagnostic-wide">
        <h3><Database size={14} aria-hidden="true" />完整可行性 Gate</h3>
        <div className="live-strategy-feasibility-grid">
          {feasibilityFields.map(([key, label]) => {
            const ready = data.feasibility[key];
            return <div className="live-strategy-feasibility-item" key={key}><div><strong>{label}</strong><FAStatusPill tone={ready ? "up" : "dim"} dot={false}>{ready ? "就绪" : "未就绪"}</FAStatusPill></div><p>{reasonFor(data, key, ready)}</p></div>;
          })}
        </div>
      </section>
      <section className="live-strategy-diagnostic-wide">
        <h3><Clock3 size={14} aria-hidden="true" />数据时间戳</h3>
        <div className="live-strategy-timestamp-list">
          {timestamps.length > 0 ? timestamps.map(([label, value]) => <span key={label}>{label} <b className="fa-num">{formatTimestamp(value)}</b></span>) : <span>后端未提供数据时间戳</span>}
        </div>
      </section>
    </div>
  );
}

export function LiveStrategyDiagnostics({ data }: { data: LiveStrategyResponse | null }) {
  if (!data) {
    return <div className="finance-panel p-3 text-[length:var(--type-body-sm)] text-[var(--fg-4)]">实时策略诊断数据不可用。</div>;
  }
  return (
    <section className="live-strategy-diagnostics-view" aria-label="实时策略技术诊断">
      <header><span className="fa-eyebrow">live_strategy.v1</span><h2>实时策略技术诊断</h2></header>
      <Diagnostics data={data} />
    </section>
  );
}

export function LiveStrategyWorkspace({ data, isLoading, error, tradeDate, dailyUpdatedAt, onRefresh }: LiveStrategyWorkspaceProps) {
  if (!data) return <LiveStrategyUnavailable isLoading={isLoading} error={error} />;
  const copy = decisionCopy[data.strategy_status];
  const level = data.market_state.nearest_level;
  const blocked = data.strategy_status === "SUSPENDED_DATA" || data.status !== "available";

  return (
    <section className="live-strategy-workspace live-strategy-workspace--focused" aria-label="XAUUSD 当前策略">
      <header className="live-strategy-focus-header">
        <div>
          <span className="fa-eyebrow">{data.asset} · 当前策略</span>
          <div className="live-strategy-focus-status">
            <h1>{copy.title}</h1>
            <FAStatusPill tone={liveStatusTone(data.strategy_status)}>{liveStatusLabel(data.strategy_status)}</FAStatusPill>
            <FAStatusPill tone={availabilityTone(data.status)}>{availabilityLabel(data.status)}</FAStatusPill>
          </div>
          <p>{updateMessageLabels[data.update_reason.reason_code ?? ""] ?? data.update_reason.message ?? "后端未提供状态说明。"}</p>
        </div>
        <div className="live-strategy-focus-time">
          <span>策略日期 <b className="fa-num">{tradeDate ?? "—"}</b></span>
          <span>日度生成 <b className="fa-num">{formatTimestamp(dailyUpdatedAt)}</b></span>
          <span>实时检查 <b className="fa-num">{formatTimestamp(data.updated_at)}</b></span>
          <span>每 15 分钟自动刷新</span>
          <button type="button" onClick={onRefresh}><RefreshCw size={13} aria-hidden="true" />立即刷新</button>
        </div>
      </header>

      <div className="live-strategy-focus-grid">
        <div><span>最新价格</span><strong className="fa-price-num">{formatNumber(data.live_market.price)}</strong><small>{marketStatusLabel(data.live_market.status)} · {data.live_market.freshness_seconds === null ? "时间未知" : `${formatNumber(data.live_market.freshness_seconds, 0)} 秒前`}</small></div>
        <div><span>最近关键位</span><strong>{strategyLabel(level?.role)} <b className="fa-num">{formatNumber(level?.value)}</b></strong><small>距离 {formatPercent(level?.distance_pct)} · ATR {formatNumber(data.market_state.atr14)}</small></div>
        <div><span>日度背景</span><strong>{strategyLabel(data.baseline.bias)} / {strategyLabel(data.baseline.market_regime)}</strong><small>置信度 {formatPercent(data.baseline.confidence === null ? null : data.baseline.confidence * 100)}</small></div>
        <div className="live-strategy-focus-action"><span>现在做什么</span><strong>{copy.action}</strong></div>
      </div>

      <div className="live-strategy-current-grid">
        <KeyLevelMap data={data} />
        <TodayWatchlist data={data} action={copy.action} />
      </div>

      <CmePositioningMap data={data} />

      {blocked ? <CompactRiskStrip data={data} /> : <ActiveSetupSummary data={data} />}

    </section>
  );
}
