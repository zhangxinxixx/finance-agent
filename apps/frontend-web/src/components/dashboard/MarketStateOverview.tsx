import type { DashboardSummary, DashboardViewModel, SignalDirection } from "@/types/dashboard";
import { ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { formatDateTime } from "@/lib/date";
import { buildIntegratedMacroSummary, buildOptionsEvidenceSummary } from "./DashboardIntegratedMacroModel";
import { translateText } from "./judgmentFormat";

interface MarketStateOverviewProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
}

function directionLabel(direction: SignalDirection) {
  if (direction === "bullish") return "偏多";
  if (direction === "bearish") return "偏空";
  return "中性";
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

function metricNumber(value: string | number | null | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value.replace(/,/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
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

export function MarketStateOverview({ summary, viewModel }: MarketStateOverviewProps) {
  const integrated = buildIntegratedMacroSummary(summary, viewModel);
  const optionsEvidence = buildOptionsEvidenceSummary(summary);
  const integratedConfidence = integrated.confidence == null ? null : Math.round(Math.max(0, Math.min(1, integrated.confidence)) * 100);
  const dataPct = integrated.dataCompleteness.pct;
  const macroResistance = uniqueLevels(integrated.macroLevels.resistance).slice(0, 1);
  const macroSupport = uniqueLevels(integrated.macroLevels.support).slice(0, 2);
  const currentPrice = metricNumber(summary.market_summary.XAUUSD.value);
  const supportBroken = currentPrice != null && macroSupport.length > 0 && currentPrice < Math.min(...macroSupport);
  const directionText = integrated.overallBias || directionLabel(integrated.direction);
  const confirmationText = normalizeText(integrated.tradeImplication);
  const riskText = normalizeText(integrated.riskNote);
  const keyLevelText = [
    macroResistance[0] == null ? null : `确认 ${formatLevel(macroResistance[0])}`,
    macroSupport[0] == null ? null : `${supportBroken ? "待收复" : "观察"} ${formatLevel(macroSupport[0])}`,
    optionsEvidence.pin === "—" ? null : `Pin ${optionsEvidence.pin}`,
  ].filter(Boolean).join(" / ") || "等待关键价位确认";
  const dataQualityText = dataPct == null
    ? integrated.dataCompleteness.label
    : `${dataPct}% · ${integrated.dataCompleteness.label}`;
  const primaryReport = summary.latest_reports.find(
    (report) => report.status === "ready" && report.type === "final_report" && report.generated_at,
  ) ?? summary.latest_reports.find(
    (report) => report.status === "ready" && report.type === "macro_report" && report.generated_at,
  );
  const reportUpdatedAt = primaryReport?.generated_at ?? summary.latest_reports.find(
    (report) => report.status === "ready" && report.generated_at,
  )?.generated_at;

  return (
    <FACard
      title="今日综合判断"
      accent="emphasis"
      density="compact"
      className="dashboard-decision-panel"
      bodyClassName="dashboard-decision-body"
      action={
        reportUpdatedAt ? (
          <div className="flex items-baseline gap-1.5">
            <span className="fa-label">报告更新</span>
            <time className="fa-num text-[length:var(--type-label)] text-[var(--fg-3)]">{formatDateTime(reportUpdatedAt)}</time>
          </div>
        ) : null
      }
    >
      <div className="dashboard-decision-grid dashboard-decision-grid--integrated">
        <div className="dashboard-decision-memo">
          <div className="dashboard-decision-memo-rule" aria-hidden="true" />
          <div className="dashboard-decision-text-block">
            <div className="dashboard-section-label">操作框架</div>
            <div className={`dashboard-decision-headline dashboard-decision-headline--${integrated.direction}`}>
              <span>{directionText}</span>
              <strong>{translateText(integrated.decisionSummary)}</strong>
            </div>
          </div>

          <div className="dashboard-decision-focus-grid">
            <div className="dashboard-decision-focus-card dashboard-decision-focus-card--primary">
              <span>交易条件</span>
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
            title="综合交易价位"
            rows={[
              ...macroResistance.map((level) => ({ label: "上方确认区", value: formatLevel(level), tone: "down" as const })),
              ...macroSupport.map((level, index) => ({
                label: supportBroken
                  ? index === 0 ? "待收复区" : "已失效线"
                  : index === 0 ? "下方观察区" : "下方失效区",
                value: formatLevel(level),
                tone: supportBroken ? "down" as const : "up" as const,
              })),
              ...integrated.quickSupports.map((support) => ({
                label: quickSupportLabel(support),
                value: formatLevel(support.level),
                tone: support.status === "broken" ? "down" as const : support.status === "active" ? "up" as const : "neutral" as const,
              })),
            ]}
          />
          <LevelRows
            title="期权结构价位"
            rows={[
              { label: "Gamma Zero", value: optionsEvidence.gammaZero, tone: "neutral" },
              { label: "Pin", value: optionsEvidence.pin, tone: "neutral" },
              { label: "Call Wall", value: optionsEvidence.callWall, tone: "down" },
              { label: "Put Wall", value: optionsEvidence.putWall, tone: "up" },
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
