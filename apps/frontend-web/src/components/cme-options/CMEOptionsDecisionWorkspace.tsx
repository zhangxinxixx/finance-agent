import { AlertTriangle, ArrowDownRight, ArrowUpRight, CircleGauge, Database, Target } from "lucide-react";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type {
  CMEOptionsDecisionKeyLevel,
  CMEOptionsDecisionResponse,
  CMEOptionsDecisionSetup,
  CMEOptionsDecisionStrategy,
} from "@/types/cme-options";
import { formatCompactNumber, translateDecisionText } from "./cmeOptionsFormat";
import { CMEOptionsSurface } from "./CMEOptionsSurface";

interface CMEOptionsDecisionWorkspaceProps {
  decision: CMEOptionsDecisionResponse | null;
  isLoading: boolean;
  error: Error | null;
}

function formatNumber(value: number | null | undefined, digits = 0) {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatSigned(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${formatNumber(value, digits)}`;
}

function formatPercent(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${formatSigned(value, 2)}%`;
}

function statusTone(status: string) {
  if (status === "available") return "up" as const;
  if (status === "partial") return "warn" as const;
  return "dim" as const;
}

function statusLabel(status: string) {
  return status === "available" ? "可用" : status === "partial" ? "部分可用" : "不可用";
}

function regimeLabel(regime: string) {
  const labels: Record<string, string> = {
    negative_gamma: "负伽马",
    positive_gamma: "正伽马",
    flip_zone: "伽马翻转区",
    unavailable: "伽马不可用",
  };
  return labels[regime] ?? regime;
}

function levelRole(role: string) {
  const labels: Record<string, string> = {
    primary_support: "主支撑",
    secondary_support: "次支撑",
    primary_resistance: "主阻力",
    secondary_resistance: "次阻力",
    magnet_pin: "吸附点",
    volatility_hub: "波动枢纽",
    gamma_flip: "伽马翻转",
    tail_protection: "尾部保护",
    retest_support_candidate: "回踩支撑候选",
    retest_resistance_candidate: "反抽阻力候选",
  };
  return labels[role] ?? role;
}

function levelValue(level: CMEOptionsDecisionKeyLevel) {
  if (level.strike !== null) return formatNumber(level.strike);
  if (level.band) return `${formatNumber(level.band.lower, 1)}–${formatNumber(level.band.upper, 1)}`;
  return "—";
}

function optionSideLabel(value: string) {
  if (value === "CALL") return "看涨";
  if (value === "PUT") return "看跌";
  if (value === "BALANCED") return "均衡";
  return translateDecisionText(value);
}

function GammaProfile({ decision }: { decision: CMEOptionsDecisionResponse }) {
  const points = decision.gamma_profile.price_grid
    .map((price, index) => ({ price, netGex: decision.gamma_profile.net_gex_values[index] }))
    .filter((point): point is { price: number; netGex: number } => point.netGex !== undefined);
  const maxMagnitude = Math.max(...points.map((point) => Math.abs(point.netGex)), 1);

  if (points.length === 0) {
    return <p className="cme-decision-empty">后端未提供伽马曲线。</p>;
  }

  return (
    <div className="cme-decision-gamma-profile" aria-label="伽马曲线">
      <div className="cme-decision-gamma-profile-heading">
        <strong>伽马曲线</strong>
        <span>{translateDecisionText(decision.gamma_profile.scope)}</span>
      </div>
      <div className="cme-decision-gamma-profile-list">
        {points.map((point) => {
          const width = `${Math.max((Math.abs(point.netGex) / maxMagnitude) * 48, 1)}%`;
          return (
            <div className="cme-decision-gamma-profile-row" key={`${point.price}-${point.netGex}`}>
              <span className="fa-num">{formatNumber(point.price, 1)}</span>
              <div className="cme-decision-gamma-profile-track" aria-hidden="true">
                <i
                  className={point.netGex < 0 ? "is-negative" : "is-positive"}
                  style={{ width }}
                />
              </div>
              <b className={`fa-num ${point.netGex < 0 ? "is-negative" : "is-positive"}`}>{formatCompactNumber(point.netGex)}</b>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StrategySetup({ title, setup }: { title: string; setup: CMEOptionsDecisionSetup | null | undefined }) {
  if (!setup) return null;
  return (
    <section className="cme-decision-setup">
      <strong>{title}</strong>
      {setup.triggers.length > 0 ? <p><span>触发</span>{setup.triggers.map(translateDecisionText).join("；")}</p> : null}
      {setup.targets.length > 0 ? <p><span>目标</span><b className="fa-num">{setup.targets.map((value) => formatNumber(value)).join(" / ")}</b></p> : null}
      {setup.invalidation.length > 0 ? <p><span>失效</span>{setup.invalidation.map(translateDecisionText).join("；")}</p> : null}
    </section>
  );
}

function StrategyPanel({ title, strategy, icon }: { title: string; strategy: CMEOptionsDecisionStrategy; icon: "intraday" | "swing" }) {
  const Icon = icon === "intraday" ? CircleGauge : Target;
  return (
    <CMEOptionsSurface className="cme-decision-strategy-panel" title={title} bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
      <div className="cme-decision-strategy">
        <div className="cme-decision-strategy-heading">
          <Icon size={15} aria-hidden="true" />
          <FAStatusPill tone={statusTone(strategy.status)}>{statusLabel(strategy.status)}</FAStatusPill>
        </div>
        {strategy.status === "unavailable" ? (
          <p className="cme-decision-unavailable-copy">{translateDecisionText(strategy.reason ?? "后端未提供该策略视图。")}</p>
        ) : (
          <>
            <div className="cme-decision-strategy-overview">
              <div>
                {strategy.summary ? <p className="cme-decision-strategy-summary">{translateDecisionText(strategy.summary)}</p> : null}
                {strategy.bias || strategy.structure_bias ? <div className="cme-decision-strategy-meta">{translateDecisionText(strategy.bias ?? strategy.structure_bias)}</div> : null}
              </div>
              <div>
                {strategy.sample_window ? <p className="cme-decision-strategy-sample"><span>样本</span><b className="fa-num">{strategy.sample_count ?? "—"}</b> · {strategy.sample_window.from} → {strategy.sample_window.to}</p> : null}
                {strategy.call_oi_change !== null && strategy.call_oi_change !== undefined ? <p className="cme-decision-strategy-sample"><span>持仓变化</span>看涨 <b className="fa-num">{formatCompactNumber(strategy.call_oi_change, "张", 2, true)}</b> · 看跌 <b className="fa-num">{formatCompactNumber(strategy.put_oi_change, "张", 2, true)}</b></p> : null}
              </div>
            </div>
            <div className="cme-decision-setup-grid">
              <StrategySetup title="多头条件" setup={strategy.long_setup} />
              <StrategySetup title="空头条件" setup={strategy.short_setup} />
            </div>
            <div className="cme-decision-strategy-details">
              {strategy.targets && strategy.targets.length > 0 ? <p className="cme-decision-targets"><span>后端目标</span><b className="fa-num">{strategy.targets.map((value) => `${formatNumber(value, 1)} 点`).join(" / ")}</b></p> : null}
              {strategy.confirmation && strategy.confirmation.length > 0 ? <p className="cme-decision-targets"><span>确认</span>{strategy.confirmation.map(translateDecisionText).join("；")}</p> : null}
            </div>
          </>
        )}
        {strategy.risk_notes.length > 0 ? <p className="cme-decision-risk-note">{translateDecisionText(strategy.risk_notes[0])}</p> : null}
      </div>
    </CMEOptionsSurface>
  );
}

function StructureDecisionPanel({ decision }: { decision: CMEOptionsDecisionResponse }) {
  const structure = decision.structure_summary;
  const intent = decision.intent_summary;
  return (
    <CMEOptionsSurface title="结构修复、机构意图与三路径" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
      <div className="cme-decision-structure-summary">
        <div><span>结构状态</span><strong>{structure.label}</strong><small>{structure.summary}</small></div>
        <div><span>机构意图</span><strong>{intent.wording ?? translateDecisionText(intent.type ?? "unavailable")}</strong><small>置信度 {formatPercent(intent.confidence === null ? null : intent.confidence * 100)}</small></div>
        <div><span>NetGEX 修复</span><strong className="fa-num">{formatCompactNumber(structure.net_gex_change)}</strong><small>{structure.repair_detected ? "负 Gamma 收窄" : "尚未确认修复"}</small></div>
        <div><span>趋势启动观察</span><strong>{structure.trend_confirmed ? "已确认" : structure.trend_launch_watch ? "观察中" : "未进入"}</strong><small>{structure.below_gamma_zero ? "价格仍在 Gamma Zero 下方" : "价格不在 Gamma Zero 下方"}</small></div>
      </div>
      <div className="cme-decision-path-grid">
        {decision.scenario_paths.map((path) => (
          <article key={path.path_id}>
            <div><strong>{path.label}</strong><FAStatusPill tone={path.status === "confirmed" ? "up" : path.status === "active" ? "warn" : "dim"}>{translateDecisionText(path.status)}</FAStatusPill></div>
            <p><span>触发</span>{path.triggers.map(translateDecisionText).join("；") || "—"}</p>
            <p><span>目标</span><b className="fa-num">{path.targets.map((value) => formatNumber(value, 1)).join(" / ") || "—"}</b></p>
            <p><span>失效</span>{path.invalidation.map(translateDecisionText).join("；") || "—"}</p>
          </article>
        ))}
        {decision.scenario_paths.length === 0 ? <p className="cme-decision-empty">后端未返回可复算的三路径。</p> : null}
      </div>
    </CMEOptionsSurface>
  );
}

function CmeOiInventoryPanel({ decision }: { decision: CMEOptionsDecisionResponse }) {
  const inventoryLevels = decision.nearby_large_oi_levels.length > 0
    ? decision.nearby_large_oi_levels
    : decision.large_oi_levels;
  const inventoryTitle = decision.nearby_large_oi_levels.length > 0
    ? "主战区大额 OI（约 ±6%）"
    : "大额 OI 点位";
  const changes = [
    ...decision.oi_change_rankings.largest_increases.slice(0, 5),
    ...decision.oi_change_rankings.largest_decreases.slice(0, 3),
  ];
  return (
    <>
      <CMEOptionsSurface title={inventoryTitle} bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
        <div className="cme-decision-table-wrap">
          <table className="cme-decision-table cme-decision-table--compact">
            <thead><tr><th>点位</th><th>期限</th><th>方向</th><th>OI</th><th>ΔOI</th></tr></thead>
            <tbody>
              {inventoryLevels.slice(0, 8).map((row) => <tr key={`${row.expiry}-${row.strike}`}><th className="fa-num">{formatNumber(row.strike)}</th><td>{row.expiry}</td><td>{optionSideLabel(row.dominant_side)}</td><td>{formatNumber(row.total_oi)}</td><td>{formatSigned(row.total_oi_change)}</td></tr>)}
            </tbody>
          </table>
        </div>
        <div className="cme-decision-pnt-summary">
          <span>PNT / Block</span>
          <strong>PNT <b className="fa-num">{formatNumber(decision.pnt_summary.pnt_totals.total)}</b></strong>
          <strong>Block <b className="fa-num">{formatNumber(decision.pnt_summary.block_totals.total)}</b></strong>
          <strong>合计 <b className="fa-num">{formatNumber(decision.pnt_summary.totals.total)}</b></strong>
          <span className="cme-decision-pnt-status">{decision.pnt_summary.block_coverage_status === "observed" ? "Block 已观测" : decision.pnt_summary.block_coverage_status === "not_verified" ? "Block 未核验" : "Block 不可用"}</span>
        </div>
      </CMEOptionsSurface>
      <CMEOptionsSurface title="近期最大增减仓" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
        <div className="cme-decision-table-wrap">
          <table className="cme-decision-table cme-decision-table--compact">
            <thead><tr><th>点位</th><th>期限</th><th>类型</th><th>当前 OI</th><th>ΔOI</th></tr></thead>
            <tbody>
              {changes.map((row, index) => <tr key={`${row.expiry}-${row.strike}-${row.option_type}-${index}`}><th className="fa-num">{formatNumber(row.strike)}</th><td>{row.expiry}</td><td>{optionSideLabel(row.option_type)}</td><td>{formatNumber(row.current_oi)}</td><td className={(row.delta ?? 0) >= 0 ? "is-positive" : "is-negative"}>{formatSigned(row.delta)}</td></tr>)}
            </tbody>
          </table>
        </div>
      </CMEOptionsSurface>
    </>
  );
}

function DecisionUnavailable({ isLoading, error }: Pick<CMEOptionsDecisionWorkspaceProps, "isLoading" | "error">) {
  return (
    <section className="cme-decision-unavailable" aria-live="polite">
      <AlertTriangle size={16} aria-hidden="true" />
      <div>
        <strong>决策视图{isLoading ? "加载中" : "不可用"}</strong>
        <p>{isLoading ? "正在读取 /api/options/decision；下方快照分析仍可使用。" : error?.message ?? "后端未返回决策 ViewModel；下方快照分析仍可使用。"}</p>
      </div>
    </section>
  );
}

export function CMEOptionsDecisionWorkspace({ decision, isLoading, error }: CMEOptionsDecisionWorkspaceProps) {
  if (!decision) return <DecisionUnavailable isLoading={isLoading} error={error} />;

  const { oi_summary: oi, gamma_summary: gamma, price_context: prices } = decision;
  const resolvedGammaRegime = gamma.regime === "negative_gamma" || gamma.regime === "positive_gamma" || gamma.regime === "flip_zone"
    ? gamma.regime
    : gamma.net_gex === null
      ? "unavailable"
      : gamma.net_gex < 0
        ? "negative_gamma"
        : gamma.net_gex > 0
          ? "positive_gamma"
          : "flip_zone";
  const primarySummary = translateDecisionText(
    decision.intraday_strategy.summary
      ?? decision.intraday_strategy.reason
      ?? "等待关键价位确认后再执行。",
  );
  return (
    <section className="cme-decision-workspace" aria-label="期权决策总览">
      <section className={`cme-decision-hero cme-decision-hero--${resolvedGammaRegime}`}>
        <div className="cme-decision-hero-copy">
          <div className="cme-decision-hero-eyebrow">
            <span>市场结构判断</span>
            <FAStatusPill tone={statusTone(decision.intraday_strategy.status)}>策略{statusLabel(decision.intraday_strategy.status)}</FAStatusPill>
          </div>
          <h2>{regimeLabel(resolvedGammaRegime)}</h2>
          <p>{primarySummary}</p>
          <div className="cme-decision-hero-meta">
            <span>{decision.meta.product}</span>
            <span>交易日 {decision.meta.current_trade_date ?? "—"}</span>
            <span>换月{statusLabel(decision.roll_summary.status)}</span>
          </div>
        </div>
        <div className="cme-decision-hero-metrics">
          <div><span>报告价 / 实时价</span><strong className="fa-num">{formatNumber(prices.report_p0, 1)} <small>/</small> {formatNumber(prices.live_p0, 1)} 点</strong></div>
          <div><span>伽马零点</span><strong className="fa-num">{formatNumber(gamma.gamma_zero, 2)} 点</strong></div>
          <div><span>净伽马敞口</span><strong className="fa-num">{formatCompactNumber(gamma.net_gex)}</strong></div>
          <div><span>总持仓单日变化</span><strong className="fa-num">{formatCompactNumber(oi.total.delta, "张", 2, true)}</strong></div>
        </div>
      </section>

      <div className={`cme-decision-strategy-grid ${decision.intraday_strategy.status === "unavailable" ? "cme-decision-strategy-grid--single" : ""}`.trim()}>
        <StrategyPanel title="日内执行策略" strategy={decision.intraday_strategy} icon="intraday" />
        <div className="cme-decision-strategy-stack">
          <StrategyPanel title="中期结构判断" strategy={decision.swing_strategy} icon="swing" />
          <CMEOptionsSurface title="数据质量" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
            <div className="cme-decision-quality"><Database size={15} aria-hidden="true" /><div><strong>{Array.isArray(decision.data_quality.cme_status) ? decision.data_quality.cme_status.map(translateDecisionText).join(" / ") : translateDecisionText(decision.data_quality.cme_status ?? "未标注")}</strong><p>{translateDecisionText(decision.data_quality.warnings[0] ?? "后端未返回额外降级提示。")}</p></div></div>
          </CMEOptionsSurface>
        </div>
      </div>

      <div className="cme-decision-layout">
        <div className="cme-decision-main">
          <StructureDecisionPanel decision={decision} />
          <CMEOptionsSurface title="伽马与换月" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
            <div className="cme-decision-gamma-grid">
              <div><span>伽马零点</span><strong className="fa-num">{formatNumber(gamma.gamma_zero, 2)} 点</strong><small>{translateDecisionText(gamma.method)}</small></div>
              <div><span>翻转区间</span><strong className="fa-num">{gamma.flip_band ? `${formatNumber(gamma.flip_band.lower, 1)}–${formatNumber(gamma.flip_band.upper, 1)} 点` : "—"}</strong><small>{gamma.flip_band ? `步长 ${formatNumber(gamma.flip_band.step, 1)} 点` : "—"}</small></div>
              <div><span>净伽马敞口</span><strong className="fa-num">{formatCompactNumber(gamma.net_gex)}</strong><small>总持仓 {formatPercent(oi.total.pct_change)}</small></div>
            </div>
            <GammaProfile decision={decision} />
            {decision.roll_summary.items.length > 0 ? <div className="cme-decision-roll-list">{decision.roll_summary.items.map((roll) => <div key={`${roll.near_expiry}-${roll.far_expiry}`}><ArrowDownRight size={14} aria-hidden="true" /><strong>{roll.near_expiry}</strong><span className="fa-num">{formatCompactNumber(roll.near_oi_delta, "张", 2, true)}</span><ArrowUpRight size={14} aria-hidden="true" /><strong>{roll.far_expiry}</strong><span className="fa-num">{formatCompactNumber(roll.far_oi_delta, "张", 2, true)}</span><small>远月看跌 {formatCompactNumber(roll.far_put_delta, "张", 2, true)} · {roll.labels.map(translateDecisionText).join(" / ") || "—"}</small></div>)}</div> : <p className="cme-decision-empty">{translateDecisionText(decision.roll_summary.reason ?? "后端未提供换月对比。")}</p>}
          </CMEOptionsSurface>

        </div>

        <aside className="cme-decision-rail">
          <CmeOiInventoryPanel decision={decision} />
          <CMEOptionsSurface title="持仓对比" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
            <div className="cme-decision-table-wrap">
              <table className="cme-decision-table cme-decision-table--compact">
                <thead><tr><th>到期</th><th>当前（张）</th><th>变化（张）</th><th>看跌（张）</th><th>看涨（张）</th></tr></thead>
                <tbody>
                  {decision.oi_by_expiry.map((row) => <tr key={row.expiry}><th>{row.expiry}</th><td>{formatNumber(row.total.current)}</td><td>{formatSigned(row.total.delta)}</td><td>{formatSigned(row.put.delta)}</td><td>{formatSigned(row.call.delta)}</td></tr>)}
                  <tr className="cme-decision-table-total"><th>合计</th><td>{formatNumber(oi.total.current)}</td><td>{formatSigned(oi.total.delta)}</td><td>{formatSigned(oi.put.delta)}</td><td>{formatSigned(oi.call.delta)}</td></tr>
                </tbody>
              </table>
            </div>
          </CMEOptionsSurface>
        </aside>
      </div>

      <CMEOptionsSurface title="关键价位与失效条件" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
        <div className="cme-decision-level-list">
          {decision.key_levels.map((level, index) => <article key={`${level.role}-${level.strike ?? level.band?.lower ?? index}`} className="cme-decision-level-row"><div><span>{levelRole(level.dynamic_role)}</span><strong className="fa-num">{levelValue(level)}</strong><small>报告角色：{levelRole(level.structural_role_at_report)}</small></div><div><span>强度 / 距离</span><p>{translateDecisionText(level.strength === null ? null : String(level.strength))} / {formatPercent(level.distance_pct)}</p></div><div><span>证据</span><p>{level.evidence.map(translateDecisionText).join("；") || "—"}</p></div><div><span>失效</span><p>{level.invalidation.map(translateDecisionText).join("；") || "—"}</p></div></article>)}
          {decision.key_levels.length === 0 ? <p className="cme-decision-empty">后端未提供关键价位。</p> : null}
        </div>
      </CMEOptionsSurface>
    </section>
  );
}
