import type { ComponentProps } from "react";
import { Shield } from "lucide-react";
import { fetchCMEOptionsDates } from "@/adapters/cmeOptions";
import { ChangeTable, ExposurePanel, GEXBreakdown, IVSkewTable, PriceLadder } from "@/components/cme-options/CMEOptionsGammaPanels";
import { CMEOptionsOverviewGrid } from "@/components/cme-options/CMEOptionsOverviewGrid";
import { CMEOptionsRightColumn } from "@/components/cme-options/CMEOptionsRightColumn";
import { translateIntent } from "@/components/cme-options/cmeOptionsFormat";
import { GammaZeroCard } from "@/components/cme-options/GammaZeroCard";
import { OptionsWallTable } from "@/components/cme-options/OptionsWallTable";
import { SourceTracePanel } from "@/components/cme-options/SourceTracePanel";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import type { CMEOptionsResponse } from "@/types/cme-options";

type NetGexAggregate = ComponentProps<typeof GammaZeroCard>["netGexAggregate"];
type SourceTraceItems = ComponentProps<typeof SourceTracePanel>["sourceTrace"];
export type CMEOptionsTab = "overview" | "gex-gamma" | "wall-map" | "scenario" | "data-trace";

export function sourceLabel(source: "api" | "mock" | "unavailable") {
  return getStatusLabel(source, "source");
}

export function sourceTone(source: "api" | "mock" | "unavailable"): FAStatusTone {
  return getStatusTone(source, "source");
}

export function reportStatusTone(status: string | undefined): FAStatusTone {
  return getStatusTone(status, "report");
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

  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-2 rounded-[var(--radius-md)] border px-3 py-1.5"
      style={{
        borderColor: "rgba(240,82,82,0.28)",
        background: "linear-gradient(135deg, rgba(240,82,82,0.12), rgba(240,82,82,0.04))",
        borderLeft: "3px solid var(--down)",
      }}
    >
      <div className="flex items-center gap-2">
        <Shield size={13} className="text-[var(--down)]" />
        <div className="flex flex-col">
          <span className="text-[8px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">当前意图</span>
          <span className="text-[13px] font-bold leading-tight text-[var(--down)]">{intentType}</span>
        </div>
      </div>
      <div className="h-6 w-px bg-[var(--border)]" />
      <div
        className="min-w-0 text-[10px] leading-snug text-[var(--fg-3)]"
        title={evidence.join(" / ") || `置信度 ${confPct}/100`}
        style={{
          maxWidth: 360,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {evidence[0] ?? `置信度 ${confPct}/100`}
      </div>
      {evidence.slice(1, 3).map((ev) => (
        <span
          key={ev}
          className="max-w-[160px] truncate rounded-[var(--radius-sm)] border px-2 py-0.5 text-[9px] font-semibold text-[var(--down)]"
          style={{ borderColor: "rgba(240,82,82,0.22)", background: "rgba(240,82,82,0.08)" }}
          title={ev}
        >
          {ev}
        </span>
      ))}
      <div className="h-6 w-px bg-[var(--border)]" />
      <div className="flex items-center gap-1.5">
        <span className="fa-num text-[16px] font-bold text-[var(--down)]" style={{ fontFamily: "var(--font-mono)" }}>{confPct}</span>
        <span className="text-[9px] text-[var(--fg-5)]">/ 100</span>
      </div>
    </div>
  );
}

export function renderCMEOptionsTabContent({
  snapshot,
  activeTab,
  wallScores,
  selectedExpiry,
}: {
  snapshot: CMEOptionsResponse;
  activeTab: CMEOptionsTab;
  wallScores: CMEOptionsResponse["wall_scores"];
  selectedExpiry: string | undefined;
}) {
  const currentPrice = snapshot?.gex?.netgex_aggregate?.gamma_zero?.price ?? 0;

  if (activeTab === "overview") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, overflowY: "auto" }}>
        <CMEOptionsOverviewGrid snapshot={snapshot} wallScores={wallScores} />
      </div>
    );
  }

  if (activeTab === "gex-gamma") {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "minmax(260px,0.8fr) minmax(0,1.4fr)", gap: 8, minHeight: 0 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, overflowY: "auto" }}>
          <PriceLadder supportResistance={snapshot.support_resistance} currentPrice={currentPrice} />
          <ChangeTable snapshot={snapshot} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, overflowY: "auto" }}>
          <GammaZeroCard netGexAggregate={snapshot.gex?.netgex_aggregate as NetGexAggregate} wallScores={wallScores} />
          <GEXBreakdown snapshot={snapshot} selectedExpiry={selectedExpiry} />
          <ExposurePanel snapshot={snapshot} />
        </div>
      </div>
    );
  }

  if (activeTab === "wall-map") {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "minmax(260px,0.7fr) minmax(0,1.3fr)", gap: 8, minHeight: 0 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, overflowY: "auto" }}>
          <PriceLadder supportResistance={snapshot.support_resistance} currentPrice={currentPrice} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, overflowY: "auto" }}>
          <OptionsWallTable wallScores={wallScores} />
        </div>
      </div>
    );
  }

  if (activeTab === "scenario") {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(320px,0.85fr)", gap: 8, minHeight: 0 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, overflowY: "auto" }}>
          <CMEOptionsOverviewGrid snapshot={snapshot} wallScores={wallScores} />
          <IVSkewTable snapshot={snapshot} />
        </div>
        <CMEOptionsRightColumn snapshot={snapshot} />
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(320px,0.85fr)", gap: 8, minHeight: 0 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, overflowY: "auto" }}>
        <IVSkewTable snapshot={snapshot} />
        <ExposurePanel snapshot={snapshot} />
        <SourceTracePanel sourceTrace={(snapshot.source_trace ?? []) as SourceTraceItems} />
      </div>
      <CMEOptionsRightColumn snapshot={snapshot} />
    </div>
  );
}
