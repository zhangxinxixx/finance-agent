import { readerSource, readerValue } from "@/lib/readerLabels";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getStatusLabel } from "@/components/shared/statusMeta";
import type { DashboardSummary } from "@/types/dashboard";

import { buildOptionsEvidenceSummary } from "./DashboardIntegratedMacroModel";
import { formatOptionalNumber, getConfidenceColor, getWallStrength, translateIntent } from "./CMEOptionsSummaryFormat";

interface CMEOptionsSummaryProps {
  options: DashboardSummary["cme_options"];
  summary: DashboardSummary;
}

function SummaryTile({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div
      className="rounded border px-2.5 py-1.5"
      style={{
        borderColor: "var(--border-faint)",
        background: "var(--bg-card-inner)",
      }}
    >
      <div className="dashboard-cme-micro-label">{label}</div>
      <div className="fa-num dashboard-cme-tile-value">
        {value}
      </div>
    </div>
  );
}

function MainLevelRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | null;
  tone: "up" | "down";
}) {
  return (
    <div className="flex items-center justify-between gap-2 rounded border px-2.5 py-1.5" style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}>
      <div className="dashboard-cme-micro-label">{label}</div>
      <div className="fa-num dashboard-cme-level-value" style={{ ["--cme-level-color" as string]: tone === "down" ? "var(--down)" : "var(--up)" }}>
        {formatOptionalNumber(value, 0)}
      </div>
    </div>
  );
}

function strongestWall(walls: DashboardSummary["cme_options"]["upper_resistance_walls"]): number | null {
  if (walls.length === 0) return null;
  return [...walls].sort((a, b) => b.score - a.score)[0]?.strike ?? null;
}

export function CMEOptionsSummary({ options, summary }: CMEOptionsSummaryProps) {
  const confidenceLevel = options.confidence?.level ?? "low";
  const confidenceColor = getConfidenceColor(confidenceLevel);
  const wallBias = getWallStrength(options.wall_score);
  const dataStatus = options.data_status || options.confidence?.data_status || "UNAVAILABLE";
  const mainResistance = strongestWall(options.upper_resistance_walls);
  const mainSupport = strongestWall(options.lower_support_walls);
  const calendarDays = options.confidence?.calendar_days ?? options.confidence?.age_days;
  const tradingDays = options.confidence?.trading_days;
  const evidenceWeight = options.confidence?.weight_multiplier;
  const evidence = buildOptionsEvidenceSummary(summary);
  const confidencePct = evidence.confidencePct;

  return (
    <div className="fa-card">
      <div className="fa-card-header !px-3 !py-2">
        <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] fa-important-bg" />
        <div className="min-w-0 flex-1">
          <div className="dashboard-cme-micro-label">期权结构摘要</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2">
            <span className="truncate" style={{ fontSize: "12px", fontWeight: 600, color: "var(--fg-2)" }}>
              芝商所期权估计结构
            </span>
            <span className="fa-num text-[10px] text-[var(--fa-text-label)]">{options.trade_date || "日期未知"}</span>
            <FAStatusPill tone="neutral" dot={false} className="whitespace-nowrap" title={wallBias.label}>
              <span style={{ color: wallBias.color }}>{wallBias.label}</span>
            </FAStatusPill>
            <FAStatusPill
              tone="neutral"
              dot={false}
              className="whitespace-nowrap"
              title={`置信度 ${confidencePct}`}
            >
              <span style={{ color: confidenceColor }}>置信 {confidencePct}</span>
            </FAStatusPill>
          </div>
        </div>
      </div>

      <div className="fa-card-body space-y-2.5" style={{ padding: "9px 12px" }}>
        <div className="dashboard-options-report-note">
          <span>结构判断</span>
          <strong>{translateIntent(options.intent)} · {wallBias.label}</strong>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <SummaryTile label="伽马翻转估计位（黄金期货）" value={formatOptionalNumber(options.gamma_zero, 1)} />
          <SummaryTile label="持仓与伽马集中位（估计）" value={formatOptionalNumber(options.pin_level, 1)} />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <MainLevelRow label="看涨持仓墙" value={mainResistance} tone="down" />
          <MainLevelRow label="看跌持仓墙" value={mainSupport} tone="up" />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <FAStatusPill status={dataStatus} domain="source" dot={false} className="whitespace-nowrap">
            {getStatusLabel(dataStatus, "source")}
          </FAStatusPill>
          {typeof tradingDays === "number" ? (
            <FAStatusPill tone="dim" dot={false} className="whitespace-nowrap">
              {`交易日龄 ${tradingDays}`}
            </FAStatusPill>
          ) : null}
          {typeof calendarDays === "number" ? (
            <FAStatusPill tone="dim" dot={false} className="whitespace-nowrap">
              {`自然日龄 ${calendarDays}`}
            </FAStatusPill>
          ) : null}
          {typeof evidenceWeight === "number" ? (
            <FAStatusPill tone="dim" dot={false} className="whitespace-nowrap">
              {`研究证据系数 ${evidenceWeight.toFixed(1)}`}
            </FAStatusPill>
          ) : null}
        </div>

        <div className="dashboard-options-report-note">
          <span>伽马敞口口径</span>
          <strong>{options.gex_semantics_label === "OI-Signed GEX Proxy" ? "持仓加权伽马敞口估计" : readerValue(options.gex_semantics_label, "敞口估计口径待中文说明")} · GC期货坐标 · 做市商方向未知</strong>
        </div>

        {evidence.analysisSummary ? (
          <section className="dashboard-options-analysis" aria-label="期权结构总结性分析">
            <div className="dashboard-options-analysis-title">结构结论</div>
            <p>{readerValue(evidence.analysisSummary, "结构结论的中文说明尚未提供，请查看已保存的来源记录。")}</p>
            {evidence.upgradeCondition ? (
              <div className="dashboard-options-condition dashboard-options-condition--upgrade">
                <span>升级条件</span>
                <strong>{evidence.upgradeCondition}</strong>
              </div>
            ) : null}
            {evidence.failureCondition ? (
              <div className="dashboard-options-condition dashboard-options-condition--failure">
                <span>失效条件</span>
                <strong>{evidence.failureCondition}</strong>
              </div>
            ) : null}
            {evidence.revisionNote ? (
              <div className="dashboard-options-revision-note">{evidence.revisionNote}</div>
            ) : null}
          </section>
        ) : null}

        <div className="dashboard-options-usage-note">{evidence.usageNote}</div>

        <ResearchDetails label="查看结构依据记录">{evidence.sourceRefs.length ? (
          <div className="dashboard-options-source-list">
            <EvidenceRecordActions record={evidence.sourceRefs} label="结构依据记录" />
            {evidence.sourceRefs.map((trace, index) => (
              <span key={`${trace.source_ref}-${trace.snapshot_id ?? index}`}>
                {readerSource(trace.name || trace.source_ref)}
              </span>
            ))}
          </div>
        ) : null}</ResearchDetails>

        <div className="flex justify-end">
          <Link
            to="/cme-options"
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border px-2.5 py-1 text-[10px] font-semibold tracking-[0] text-[var(--fg-3)] transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-panel)] hover:text-[var(--fg-2)]"
            style={{
              borderColor: "var(--border-faint)",
              background: "var(--bg-card-inner)",
            }}
          >
            查看期权结构
            <ArrowRight size={11} />
          </Link>
        </div>
      </div>
    </div>
  );
}
