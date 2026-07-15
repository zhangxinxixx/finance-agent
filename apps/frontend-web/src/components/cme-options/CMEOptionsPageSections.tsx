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
  const confPct = Math.round((snapshot.intent.confidence ?? snapshot.intent.score ?? 0) * 100);
  const evidence = snapshot.intent.evidence ?? [];
  const localizedEvidence = evidence.map((ev) => translateEvidence(ev));

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
        title={localizedEvidence.join(" / ") || `置信度 ${confPct}/100`}
        style={{
          maxWidth: 260,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {localizedEvidence[0] ?? `置信度 ${confPct}/100`}
      </div>
      <div className="flex items-center gap-1.5">
        <span className="cme-options-intent-score fa-num">{confPct}</span>
        <span className="cme-options-intent-score-unit">/ 100</span>
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
  const currentPrice = snapshot.parameters?.f_value
    ?? snapshot.parameters?.report_p0
    ?? snapshot.gex?.netgex_aggregate?.gamma_zero?.price
    ?? 0;

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
          <PriceLadder supportResistance={snapshot.support_resistance} currentPrice={currentPrice} />
          <ChangeTable snapshot={snapshot} />
        </div>
        <div className="cme-options-tab-stack">
          <GammaZeroCard netGexAggregate={snapshot.gex?.netgex_aggregate} decisionGamma={decision?.gamma_summary} wallScores={wallScores} />
          <GEXBreakdown snapshot={snapshot} selectedExpiry={selectedExpiry} />
          <ExposurePanel snapshot={snapshot} />
        </div>
      </div>
    );
  }

  if (activeTab === "wall-map") {
    return (
      <div className="cme-options-tab-grid cme-options-tab-grid--wall-map">
        <div className="cme-options-tab-stack">
          <PriceLadder supportResistance={snapshot.support_resistance} currentPrice={currentPrice} />
        </div>
        <div className="cme-options-tab-stack">
          <OptionsWallTable wallScores={wallScores} />
        </div>
      </div>
    );
  }

  if (activeTab === "scenario") {
    return (
      <div className="cme-options-tab-grid cme-options-tab-grid--right-rail">
        <div className="cme-options-tab-stack">
          <IVSkewTable snapshot={snapshot} />
          <ExposurePanel snapshot={snapshot} />
        </div>
        <CMEOptionsRightColumn snapshot={snapshot} decision={decision} />
      </div>
    );
  }

  return (
    <div className="cme-options-tab-grid cme-options-tab-grid--right-rail">
      <div className="cme-options-tab-stack">
        <SourceTracePanel sourceTrace={(snapshot.source_trace ?? []) as SourceTraceItems} />
      </div>
      <CMEOptionsRightColumn snapshot={snapshot} decision={decision} />
    </div>
  );
}
