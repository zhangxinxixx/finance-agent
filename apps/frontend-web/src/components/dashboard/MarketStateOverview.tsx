import type { DashboardSummary, DashboardViewModel, SignalDirection } from "@/types/dashboard";
import { ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
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

function compactText(value: string): string {
  const text = translateText(value).replace(/\s+/g, " ").trim();
  return text.length > 72 ? `${text.slice(0, 72).trim()}...` : text;
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
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function uniqueLevels(levels: number[]): number[] {
  const seen = new Set<number>();
  return levels.filter((level) => {
    if (seen.has(level)) return false;
    seen.add(level);
    return true;
  });
}

export function MarketStateOverview({ summary, viewModel }: MarketStateOverviewProps) {
  const integrated = buildIntegratedMacroSummary(summary, viewModel);
  const optionsEvidence = buildOptionsEvidenceSummary(summary);
  const integratedConfidence = integrated.confidence == null ? null : Math.round(Math.max(0, Math.min(1, integrated.confidence)) * 100);
  const dataPct = integrated.dataCompleteness.pct;
  const macroResistance = uniqueLevels(integrated.macroLevels.resistance).slice(0, 1);
  const macroSupport = uniqueLevels(integrated.macroLevels.support).slice(0, 2);
  const directionText = directionLabel(integrated.direction);
  const confirmationText = compactText(integrated.tradeImplication);
  const riskText = compactText(integrated.riskNote);
  const keyLevelText = [
    macroResistance[0] == null ? null : `确认 ${formatLevel(macroResistance[0])}`,
    macroSupport[0] == null ? null : `观察 ${formatLevel(macroSupport[0])}`,
    optionsEvidence.pin === "—" ? null : `Pin ${optionsEvidence.pin}`,
  ].filter(Boolean).join(" / ") || "等待关键价位确认";
  const dataQualityText = dataPct == null
    ? integrated.dataCompleteness.label
    : `${dataPct}% · ${integrated.dataCompleteness.label}`;

  return (
    <FACard
      title="今日综合判断"
      accent="emphasis"
      density="compact"
      className="dashboard-decision-panel"
      bodyClassName="dashboard-decision-body"
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
            title="宏观交易价位"
            rows={[
              ...macroResistance.map((level) => ({ label: "上方确认区", value: formatLevel(level), tone: "down" as const })),
              ...macroSupport.map((level, index) => ({
                label: index === 0 ? "下方观察区" : "下方失效区",
                value: formatLevel(level),
                tone: "up" as const,
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
