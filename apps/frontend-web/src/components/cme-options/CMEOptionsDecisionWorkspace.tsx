import { AlertTriangle, ArrowDownRight, ArrowUpRight, CircleGauge, Database, Target } from "lucide-react";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type {
  CMEOptionsDecisionKeyLevel,
  CMEOptionsDecisionResponse,
  CMEOptionsDecisionSetup,
  CMEOptionsDecisionStrategy,
} from "@/types/cme-options";
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
    flip_zone: "Gamma 翻转区",
    unavailable: "Gamma 不可用",
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
    gamma_flip: "Gamma 翻转",
    tail_protection: "尾部保护",
  };
  return labels[role] ?? role;
}

function levelValue(level: CMEOptionsDecisionKeyLevel) {
  if (level.strike !== null) return formatNumber(level.strike);
  if (level.band) return `${formatNumber(level.band.lower, 1)}–${formatNumber(level.band.upper, 1)}`;
  return "—";
}

function GammaProfile({ decision }: { decision: CMEOptionsDecisionResponse }) {
  const points = decision.gamma_profile.price_grid
    .map((price, index) => ({ price, netGex: decision.gamma_profile.net_gex_values[index] }))
    .filter((point): point is { price: number; netGex: number } => point.netGex !== undefined);
  const maxMagnitude = Math.max(...points.map((point) => Math.abs(point.netGex)), 1);

  if (points.length === 0) {
    return <p className="cme-decision-empty">后端未提供 Gamma Profile。</p>;
  }

  return (
    <div className="cme-decision-gamma-profile" aria-label="Gamma Profile">
      <div className="cme-decision-gamma-profile-heading">
        <strong>Gamma Profile</strong>
        <span>{decision.gamma_profile.scope}</span>
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
              <b className={`fa-num ${point.netGex < 0 ? "is-negative" : "is-positive"}`}>{formatSigned(point.netGex, 2)}</b>
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
      {setup.triggers.length > 0 ? <p><span>触发</span>{setup.triggers.join("；")}</p> : null}
      {setup.targets.length > 0 ? <p><span>目标</span><b className="fa-num">{setup.targets.map((value) => formatNumber(value)).join(" / ")}</b></p> : null}
      {setup.invalidation.length > 0 ? <p><span>失效</span>{setup.invalidation.join("；")}</p> : null}
    </section>
  );
}

function StrategyPanel({ title, strategy, icon }: { title: string; strategy: CMEOptionsDecisionStrategy; icon: "intraday" | "swing" }) {
  const Icon = icon === "intraday" ? CircleGauge : Target;
  return (
    <CMEOptionsSurface title={title} bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
      <div className="cme-decision-strategy">
        <div className="cme-decision-strategy-heading">
          <Icon size={15} aria-hidden="true" />
          <FAStatusPill tone={statusTone(strategy.status)}>{statusLabel(strategy.status)}</FAStatusPill>
        </div>
        {strategy.status === "unavailable" ? (
          <p className="cme-decision-unavailable-copy">{strategy.reason ?? "后端未提供该策略视图。"}</p>
        ) : (
          <>
            {strategy.summary ? <p className="cme-decision-strategy-summary">{strategy.summary}</p> : null}
            {strategy.bias || strategy.structure_bias ? <div className="cme-decision-strategy-meta">{strategy.bias ?? strategy.structure_bias}</div> : null}
            {strategy.sample_window ? <p className="cme-decision-strategy-sample"><span>样本</span><b className="fa-num">{strategy.sample_count ?? "—"}</b> · {strategy.sample_window.from} → {strategy.sample_window.to}</p> : null}
            {strategy.call_oi_change !== null && strategy.call_oi_change !== undefined ? <p className="cme-decision-strategy-sample"><span>OI</span>Call <b className="fa-num">{formatSigned(strategy.call_oi_change)}</b> · Put <b className="fa-num">{formatSigned(strategy.put_oi_change)}</b></p> : null}
            <StrategySetup title="多头条件" setup={strategy.long_setup} />
            <StrategySetup title="空头条件" setup={strategy.short_setup} />
            {strategy.targets && strategy.targets.length > 0 ? <p className="cme-decision-targets"><span>后端目标</span><b className="fa-num">{strategy.targets.map((value) => formatNumber(value)).join(" / ")}</b></p> : null}
            {strategy.confirmation && strategy.confirmation.length > 0 ? <p className="cme-decision-targets"><span>确认</span>{strategy.confirmation.join("；")}</p> : null}
          </>
        )}
        {strategy.risk_notes.length > 0 ? <p className="cme-decision-risk-note">{strategy.risk_notes[0]}</p> : null}
      </div>
    </CMEOptionsSurface>
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
  return (
    <section className="cme-decision-workspace" aria-label="期权决策总览">
      <CMEOptionsSurface title="决策摘要" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
        <div className="cme-decision-summary-row">
          <div><span>Gamma 环境</span><strong>{regimeLabel(gamma.regime)}</strong></div>
          <div><span>总 OI 1D</span><strong className="fa-num">{formatSigned(oi.total.delta)}</strong></div>
          <div><span>换月状态</span><FAStatusPill tone={statusTone(decision.roll_summary.status)}>{statusLabel(decision.roll_summary.status)}</FAStatusPill></div>
          <div><span>日内策略</span><FAStatusPill tone={statusTone(decision.intraday_strategy.status)}>{statusLabel(decision.intraday_strategy.status)}</FAStatusPill></div>
          <div><span>报告 / Live</span><strong className="fa-num">{formatNumber(prices.report_p0, 1)} / {formatNumber(prices.live_p0, 1)}</strong></div>
        </div>
      </CMEOptionsSurface>

      <div className="cme-decision-layout">
        <div className="cme-decision-main">
          <CMEOptionsSurface title="持仓对比" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
            <div className="cme-decision-table-wrap">
              <table className="cme-decision-table">
                <thead><tr><th>到期</th><th>当前 OI</th><th>前日 OI</th><th>1D 变化</th><th>Put 变化</th><th>Call 变化</th></tr></thead>
                <tbody>
                  {decision.oi_by_expiry.map((row) => <tr key={row.expiry}><th>{row.expiry}</th><td>{formatNumber(row.total.current)}</td><td>{formatNumber(row.total.previous)}</td><td>{formatSigned(row.total.delta)}</td><td>{formatSigned(row.put.delta)}</td><td>{formatSigned(row.call.delta)}</td></tr>)}
                  <tr className="cme-decision-table-total"><th>合计</th><td>{formatNumber(oi.total.current)}</td><td>{formatNumber(oi.total.previous)}</td><td>{formatSigned(oi.total.delta)}</td><td>{formatSigned(oi.put.delta)}</td><td>{formatSigned(oi.call.delta)}</td></tr>
                </tbody>
              </table>
            </div>
          </CMEOptionsSurface>

          <CMEOptionsSurface title="Gamma 与换月" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
            <div className="cme-decision-gamma-grid">
              <div><span>Gamma Zero</span><strong className="fa-num">{formatNumber(gamma.gamma_zero, 2)}</strong><small>{gamma.method ?? "—"}</small></div>
              <div><span>翻转区间</span><strong className="fa-num">{gamma.flip_band ? `${formatNumber(gamma.flip_band.lower, 1)}–${formatNumber(gamma.flip_band.upper, 1)}` : "—"}</strong><small>{gamma.flip_band ? `步长 ${formatNumber(gamma.flip_band.step, 1)}` : "—"}</small></div>
              <div><span>Net GEX</span><strong className="fa-num">{formatSigned(gamma.net_gex, 2)}</strong><small>总 OI {formatPercent(oi.total.pct_change)}</small></div>
            </div>
            <GammaProfile decision={decision} />
            {decision.roll_summary.items.length > 0 ? <div className="cme-decision-roll-list">{decision.roll_summary.items.map((roll) => <div key={`${roll.near_expiry}-${roll.far_expiry}`}><ArrowDownRight size={14} aria-hidden="true" /><strong>{roll.near_expiry}</strong><span className="fa-num">{formatSigned(roll.near_oi_delta)}</span><ArrowUpRight size={14} aria-hidden="true" /><strong>{roll.far_expiry}</strong><span className="fa-num">{formatSigned(roll.far_oi_delta)}</span><small>Put {formatSigned(roll.far_put_delta)} · {roll.labels.join(" / ") || "—"}</small></div>)}</div> : <p className="cme-decision-empty">{decision.roll_summary.reason ?? "后端未提供换月对比。"}</p>}
          </CMEOptionsSurface>

          <CMEOptionsSurface title="关键价位轴" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
            <div className="cme-decision-level-list">
              {decision.key_levels.map((level, index) => <article key={`${level.role}-${level.strike ?? level.band?.lower ?? index}`} className="cme-decision-level-row"><div><span>{levelRole(level.role)}</span><strong className="fa-num">{levelValue(level)}</strong></div><div><span>强度 / 距离</span><p>{level.strength ?? "—"} / {formatPercent(level.distance_pct)}</p></div><div><span>证据</span><p>{level.evidence.join("；") || "—"}</p></div><div><span>失效</span><p>{level.invalidation.join("；") || "—"}</p></div></article>)}
              {decision.key_levels.length === 0 ? <p className="cme-decision-empty">后端未提供关键价位。</p> : null}
            </div>
          </CMEOptionsSurface>
        </div>

        <aside className="cme-decision-rail">
          <StrategyPanel title="日内策略" strategy={decision.intraday_strategy} icon="intraday" />
          <StrategyPanel title="中期结构" strategy={decision.swing_strategy} icon="swing" />
          <CMEOptionsSurface title="数据质量" bodyStyle={{ padding: 0, background: "var(--bg-card-inner)" }}>
            <div className="cme-decision-quality"><Database size={15} aria-hidden="true" /><div><strong>{Array.isArray(decision.data_quality.cme_status) ? decision.data_quality.cme_status.join(" / ") : decision.data_quality.cme_status ?? "未标注"}</strong><p>{decision.data_quality.warnings[0] ?? "后端未返回额外降级提示。"}</p></div></div>
          </CMEOptionsSurface>
        </aside>
      </div>
    </section>
  );
}
