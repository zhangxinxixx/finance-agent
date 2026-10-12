import type { DashboardSummary, DashboardViewModel, SignalDirection } from "@/types/dashboard";
import { ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { formatDateTime } from "@/lib/date";
import { buildIntegratedMacroSummary, buildOptionsEvidenceSummary, dashboardResearchAsOf } from "./DashboardIntegratedMacroModel";
import { translateText } from "./judgmentFormat";

interface MarketStateOverviewProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
}

function directionLabel(direction: SignalDirection | "unknown") {
  if (direction === "bullish") return "偏多";
  if (direction === "bearish") return "偏空";
  return direction === "neutral" ? "中性" : "方向未提供";
}

function normalizeText(value: string): string {
  return translateText(value).replace(/\s+/g, " ").trim();
}

function LevelRows({ title, rows }: { title: string; rows: Array<{ label: string; value: string; tone?: "up" | "down" | "neutral" }> }) {
  return (
    <div className="dashboard-level-group">
      <div className="dashboard-section-label">{title}</div>
      <div className="dashboard-level-list">
        {rows.map((row) => (
          <div key={`${title}-${row.label}-${row.value}`} className={`dashboard-level-row dashboard-level-row--${row.tone ?? "neutral"}`}>
            <span>{row.label}</span>
            <strong>{row.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatLevel(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

function uniqueLevels(levels: number[]): number[] {
  const seen = new Set<number>();
  return levels.filter((level) => {
    if (seen.has(level)) return false;
    seen.add(level);
    return true;
  });
}

function compactDate(value: string | null): string {
  const match = value?.match(/^\d{4}-(\d{2})-(\d{2})/);
  return match ? `${match[1]}-${match[2]}` : "日期待确认";
}

function quickSupportLabel(
  support: { source_label: string; trade_date: string | null; timeframe: string | null; status: "active" | "broken" | "unknown" },
): string {
  const state = support.status === "broken" ? "已跌破" : support.status === "active" ? "支撑观察" : "状态待确认";
  const timeframe = support.timeframe ? ` ${support.timeframe}` : "";
  return `${support.source_label}${timeframe} · ${compactDate(support.trade_date)} · ${state}`;
}

type LevelCoordinate = "spot" | "gc_futures" | "unknown";

function levelGroupTitle(resistance: LevelCoordinate, support: LevelCoordinate): string {
  if (resistance === "spot" && support === "spot") return "现货执行区";
  if (resistance === "gc_futures" && support === "gc_futures") return "GC 期货观察区";
  if (resistance === "unknown" && support === "unknown") return "来源待确认价位";
  return "多坐标价位观察";
}

function resistanceLabel(coordinate: LevelCoordinate): string {
  if (coordinate === "spot") return "现货上方确认区";
  if (coordinate === "gc_futures") return "GC 期货阻力观察";
  return "阻力观察（来源待确认）";
}

function supportLabel(coordinate: LevelCoordinate, index: number, supportBroken: boolean): string {
  if (coordinate === "gc_futures") return index === 0 ? "GC 期货支撑观察" : "GC 期货次级支撑观察";
  if (coordinate === "unknown") return index === 0 ? "支撑观察（来源待确认）" : "次级支撑观察（来源待确认）";
  if (supportBroken) return index === 0 ? "现货待收复区" : "现货已失效线";
  return index === 0 ? "现货下方观察区" : "现货下方失效区";
}

function compactLevelLabel(coordinate: LevelCoordinate, kind: "resistance" | "support", supportBroken = false): string {
  if (coordinate === "gc_futures") return kind === "resistance" ? "GC 阻力观察" : "GC 支撑观察";
  if (coordinate === "unknown") return kind === "resistance" ? "阻力（来源待确认）" : "支撑（来源待确认）";
  if (kind === "resistance") return "现货确认";
  return supportBroken ? "现货待收复" : "现货观察";
}

export function MarketStateOverview({ summary, viewModel }: MarketStateOverviewProps) {
  const observationOnly = summary.integrated_macro?.authority === "observation_only"
    || summary.integrated_macro?.publish_allowed === false;
  const integrated = buildIntegratedMacroSummary(summary, viewModel);
  const optionsEvidence = buildOptionsEvidenceSummary(summary);
  const integratedConfidence = integrated.confidence == null ? null : Math.round(Math.max(0, Math.min(1, integrated.confidence)) * 100);
  const dataPct = integrated.dataCompleteness.pct;
  const macroResistance = uniqueLevels(integrated.macroLevels.resistance).slice(0, 1);
  const macroSupport = uniqueLevels(integrated.macroLevels.support).slice(0, 2);
  // Current invalidation is a backend decision; comparing a quote here cannot verify it.
  const supportBroken = false;
  const directionText = integrated.overallBias || (integrated.direction === "unknown" ? "方向待确认" : directionLabel(integrated.direction));
  const confirmationText = normalizeText(integrated.tradeImplication);
  const riskText = normalizeText(integrated.riskNote);
  const keyLevelText = [
    macroResistance[0] == null ? null : `${compactLevelLabel(integrated.macroLevels.resistanceCoordinate, "resistance")} ${formatLevel(macroResistance[0])}`,
    macroSupport[0] == null ? null : `${compactLevelLabel(integrated.macroLevels.supportCoordinate, "support", supportBroken)} ${formatLevel(macroSupport[0])}`,
    optionsEvidence.pin === "—" ? null : `持仓伽马集中位（黄金期货估计）${optionsEvidence.pin}`,
  ].filter(Boolean).join(" / ") || "等待关键价位确认";
  const dataQualityText = dataPct == null
    ? integrated.dataCompleteness.label
    : `${dataPct}% · ${integrated.dataCompleteness.label}`;
  const conclusionAsOf = dashboardResearchAsOf(summary, viewModel);

  return (
    <FACard
      title={observationOnly ? "当前研究观察" : "已有综合判断"}
      accent="emphasis"
      density="compact"
      className="dashboard-decision-panel"
      bodyClassName="dashboard-decision-body"
      action={
        conclusionAsOf ? (
          <div className="flex items-baseline gap-1.5">
            <span className="fa-label">结论时间</span>
            <time className="fa-num text-[length:var(--type-label)] text-[var(--fg-3)]">{formatDateTime(conclusionAsOf)}</time>
          </div>
        ) : null
      }
    >
      <div className="dashboard-decision-grid dashboard-decision-grid--integrated">
        <div className="dashboard-decision-memo">
          <div className="dashboard-decision-memo-rule" aria-hidden="true" />
          <div className="dashboard-decision-text-block">
            <div className="dashboard-section-label">{observationOnly ? "研究结论 · 不代表正式策略" : "研究框架"}</div>
            <div className={`dashboard-decision-headline dashboard-decision-headline--${integrated.direction}`}>
              <span>{directionText}</span>
              <strong>{translateText(integrated.decisionSummary)}</strong>
            </div>
          </div>

          <div className="dashboard-decision-focus-grid">
            <div className="dashboard-decision-focus-card dashboard-decision-focus-card--primary">
              <span>{observationOnly ? "待验证条件" : "交易条件"}</span>
              <strong>{confirmationText}</strong>
            </div>
            <div className="dashboard-decision-focus-card">
              <span>关键价位</span>
              <strong>{keyLevelText}</strong>
            </div>
            <div className="dashboard-decision-focus-card dashboard-decision-focus-card--risk">
              <span>
                <ShieldAlert size={11} />
                风险线
              </span>
              <strong>{riskText}</strong>
            </div>
          </div>
        </div>

        <div className="dashboard-decision-section dashboard-decision-side">
          <LevelRows
            title={levelGroupTitle(integrated.macroLevels.resistanceCoordinate, integrated.macroLevels.supportCoordinate)}
            rows={[
              ...macroResistance.map((level) => ({
                label: resistanceLabel(integrated.macroLevels.resistanceCoordinate),
                value: formatLevel(level),
                tone: "down" as const,
              })),
              ...macroSupport.map((level, index) => ({
                label: supportLabel(integrated.macroLevels.supportCoordinate, index, supportBroken),
                value: formatLevel(level),
                tone: integrated.macroLevels.supportCoordinate === "spot" && supportBroken ? "down" as const : "up" as const,
              })),
              ...integrated.quickSupports.map((support) => ({
                label: quickSupportLabel(support),
                value: formatLevel(support.level),
                tone: support.status === "broken" ? "down" as const : support.status === "active" ? "up" as const : "neutral" as const,
              })),
            ]}
          />
          <LevelRows
            title={`期权结构价位 · GC · ${summary.cme_options.trade_date || "交易日未知"}`}
            rows={[
              { label: "伽马翻转估计位（黄金期货）", value: optionsEvidence.gammaZero, tone: "neutral" },
              { label: "持仓与伽马集中位（估计）", value: optionsEvidence.pin, tone: "neutral" },
              { label: "看涨持仓墙", value: optionsEvidence.callWall, tone: "down" },
              { label: "看跌持仓墙", value: optionsEvidence.putWall, tone: "up" },
            ]}
          />
        </div>

        <div className="dashboard-quality-compact dashboard-quality-strip">
          <div className="dashboard-quality-row dashboard-quality-row--highlight">
            <span>质量</span>
            <strong>
              置信度 {integratedConfidence == null ? "—" : `${integratedConfidence}/100`} · 期权 {optionsEvidence.confidencePct}
            </strong>
          </div>
          <div className="dashboard-quality-row">
            <span>数据</span>
            <strong>{dataQualityText} · 链路 {integrated.dataCompleteness.ok}/{integrated.dataCompleteness.total || "—"}</strong>
          </div>
        </div>
      </div>
    </FACard>
  );
}
