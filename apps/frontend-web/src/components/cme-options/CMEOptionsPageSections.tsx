import { ResearchDetails } from "@/components/shared/ResearchDetails";
import type { ComponentProps } from "react";
import { Shield } from "lucide-react";
import { fetchCMEOptionsDates } from "@/adapters/cmeOptions";
import { ChangeTable, ExposurePanel, GEXBreakdown, IVSkewTable, PriceLadder } from "@/components/cme-options/CMEOptionsGammaPanels";
import { CMEOptionsOverviewGrid } from "@/components/cme-options/CMEOptionsOverviewGrid";
import { CMEOptionsRightColumn } from "@/components/cme-options/CMEOptionsRightColumn";
import { translateEvidence, translateIntent } from "@/components/cme-options/cmeOptionsFormat";
import { GammaZeroCard } from "@/components/cme-options/GammaZeroCard";
import { OptionsWallTable } from "@/components/cme-options/OptionsWallTable";
import { SourceTracePanel } from "@/components/cme-options/SourceTracePanel";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import type { CMEOptionsDecisionResponse, CMEOptionsResponse } from "@/types/cme-options";
type SourceTraceItems = ComponentProps<typeof SourceTracePanel>["sourceTrace"];
export type CMEOptionsTab = "overview" | "snapshot-overview" | "gex-gamma" | "wall-map" | "scenario" | "data-trace";

export function sourceLabel(source: "api" | "mock" | "unavailable") {
  return getStatusLabel(source, "source");
}

export function sourceTone(source: "api" | "mock" | "unavailable"): FAStatusTone {
  return getStatusTone(source, "source");
}

export function reportStatusTone(status: string | undefined): FAStatusTone {
  return getStatusTone(status, "report");
}

export function reportStatusLabel(status: string | undefined): string {
  if (status === "FINAL") return "终版";
  if (status === "PRELIM") return "预览";
  return getStatusLabel(status, "report");
}

export function reviewStatusTone(status: string | null | undefined): FAStatusTone {
  return getStatusTone(status, "review");
}

export function reviewStatusLabel(status: string | null | undefined): string {
  return getStatusLabel(status, "review");
}

export function CMEOptionsLoadingShell() {
  return (
    <div className="space-y-3">
      <LoadingSkeleton variant="page" />
      <div className="grid gap-3 xl:grid-cols-2">
        <LoadingSkeleton variant="table" rows={6} />
        <LoadingSkeleton variant="panel" rows={7} />
      </div>
    </div>
  );
}

export function CMEOptionsIntentSummary({ snapshot }: { snapshot: CMEOptionsResponse | null }) {
  if (!snapshot?.intent) return null;

  const intentType = translateIntent(snapshot.intent.type);
  const confidence = snapshot.intent.confidence;
  const confidenceLabel = confidence === null || confidence === undefined ? "—" : `${Math.round(confidence * 100)}/100（非概率）`;
  const scoreLabel = snapshot.intent.score === null || snapshot.intent.score === undefined
    ? null
    : `评分 ${snapshot.intent.score.toLocaleString("en-US", { maximumFractionDigits: 4 })}（评分，非概率）`;
  const evidence = snapshot.intent.evidence ?? [];
  const localizedEvidence = evidence.map((ev) => translateEvidence(ev));
  const evidenceLabel = localizedEvidence.length > 0 ? localizedEvidence.join(" / ") : "未提供意图证据";

  return (
    <div
      className="cme-options-intent-summary"
      style={{
        borderColor: "var(--fa-important-border)",
        background: "var(--fa-important-soft)",
      }}
    >
      <div className="flex items-center gap-2">
        <Shield size={13} className="text-[var(--fa-important)]" />
        <div className="flex items-center gap-1.5">
          <span className="fa-compact-label">当前意图</span>
          <span className="cme-options-intent-title">{intentType}</span>
        </div>
      </div>
      <div
        className="cme-options-intent-evidence"
        style={{
          maxWidth: 420,
          overflow: "visible",
          textOverflow: "clip",
          whiteSpace: "normal",
        }}
      >
        {evidenceLabel}
      </div>
      <div className="flex items-center gap-1.5">
        <span className="cme-options-intent-score fa-num">{confidenceLabel}</span>
        <span className="cme-options-intent-score-unit">置信度</span>
        {scoreLabel ? <span className="cme-options-intent-score-unit">{scoreLabel}</span> : null}
      </div>
    </div>
  );
}

export function renderCMEOptionsTabContent({
  snapshot,
  activeTab,
  wallScores,
  selectedExpiry,
  decision,
}: {
  snapshot: CMEOptionsResponse;
  activeTab: CMEOptionsTab;
  wallScores: CMEOptionsResponse["wall_scores"];
  selectedExpiry: string | undefined;
  decision?: CMEOptionsDecisionResponse | null;
}) {
  const reportAnchor = snapshot.parameters?.report_p0 ?? snapshot.parameters?.p0 ?? null;

  if (activeTab === "overview" || activeTab === "snapshot-overview") {
    return (
      <div className="cme-options-tab-stack">
        <CMEOptionsOverviewGrid snapshot={snapshot} wallScores={wallScores} decision={decision} />
      </div>
    );
  }

  if (activeTab === "gex-gamma") {
    return (
      <div className="cme-options-tab-grid cme-options-tab-grid--left-rail">
        <div className="cme-options-tab-stack">
          <PriceLadder supportResistance={snapshot.support_resistance} currentPrice={reportAnchor} />
          <ChangeTable snapshot={snapshot} />
        </div>
        <div className="cme-options-tab-stack">
          <GammaZeroCard netGexAggregate={snapshot.gex?.netgex_aggregate} decisionGamma={decision?.gamma_summary} wallScores={wallScores} />
          <GEXBreakdown snapshot={snapshot} selectedExpiry={selectedExpiry} />
          <ExposurePanel snapshot={snapshot} selectedExpiry={selectedExpiry} />
        </div>
      </div>
    );
  }

  if (activeTab === "wall-map") {
    return (
      <div className="cme-options-tab-grid cme-options-tab-grid--wall-map">
        <div className="cme-options-tab-stack">
          <PriceLadder supportResistance={snapshot.support_resistance} currentPrice={reportAnchor} />
        </div>
        <div className="cme-options-tab-stack">
          <OptionsWallTable wallScores={wallScores} selectedExpiry={selectedExpiry} />
        </div>
      </div>
    );
  }

  if (activeTab === "scenario") {
    return (
      <div className="cme-options-tab-grid cme-options-tab-grid--right-rail">
        <div className="cme-options-tab-stack">
          <IVSkewTable snapshot={snapshot} selectedExpiry={selectedExpiry} />
          <ExposurePanel snapshot={snapshot} selectedExpiry={selectedExpiry} />
        </div>
        <CMEOptionsRightColumn snapshot={snapshot} decision={decision} />
      </div>
    );
  }

  return (
    <div className="cme-options-tab-grid cme-options-tab-grid--right-rail">
      <div className="cme-options-tab-stack">
        <ResearchDetails label="查看数据记录"><SourceTracePanel sourceTrace={(snapshot.source_trace ?? []) as SourceTraceItems} /></ResearchDetails>
      </div>
      <CMEOptionsRightColumn snapshot={snapshot} decision={decision} />
    </div>
  );
}
