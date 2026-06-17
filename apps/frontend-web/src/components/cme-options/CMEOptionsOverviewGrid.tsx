import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, formatNumber, toneStyle, topWall, translateIntent } from "./cmeOptionsFormat";
import { CMEOptionsSurface } from "./CMEOptionsSurface";

interface CMEOptionsOverviewGridProps {
  snapshot: CMEOptionsResponse;
  wallScores: CMEOptionsResponse["wall_scores"];
}

function reportStatusTone(status: string | undefined) {
  return getStatusTone(status, "report");
}

function reviewStatusTone(status: string | null | undefined) {
  return getStatusTone(status, "review");
}

function reviewStatusLabel(status: string | null | undefined): string {
  return getStatusLabel(status, "review");
}

export function CMEOptionsOverviewGrid({ snapshot, wallScores }: CMEOptionsOverviewGridProps) {
  const gex = snapshot.gex?.netgex_aggregate;
  const callWall = topWall(wallScores, "CALL");
  const putWall = topWall(wallScores, "PUT");
  const analysis = snapshot.analysis;
  const primarySummary = analysis?.synthesis?.summary || analysis?.cme_options_agent?.summary || "当前未返回后端解释摘要。";
  const nextRisk = analysis?.pending_reviews[0]?.reason
    || analysis?.synthesis?.risk_points[0]
    || analysis?.cme_options_agent?.risk_points[0]
    || "暂无额外风险提示。";

  const entries = [
    {
      label: "GEX / Gamma",
      title: formatNumber(gex?.gamma_zero?.price, 1),
      detail: `Net GEX ${formatNumber(gex?.net_gex)} · ${gex?.net_gex_direction ?? "neutral"}`,
      tone: "info",
    },
    {
      label: "Wall Map",
      title: `${formatNumber(putWall?.strike)}P / ${formatNumber(callWall?.strike)}C`,
      detail: "支撑阻力墙位进入 Wall Map 查看",
      tone: "warn",
    },
    {
      label: "Scenario",
      title: translateIntent(snapshot.intent?.type),
      detail: `confidence ${Math.round((snapshot.intent?.confidence ?? snapshot.intent?.score ?? 0) * 100)}/100`,
      tone: "down",
    },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) minmax(280px,0.8fr)", gap: 8 }}>
      <CMEOptionsSurface title="Options Overview" bodyStyle={{ display: "grid", gap: 10 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}>
          {entries.map((entry) => {
            const tone = toneStyle(entry.tone);
            return (
              <div key={entry.label} style={{ border: `1px solid ${tone.border}`, borderRadius: "var(--radius-lg)", background: "var(--bg-card-inner)", padding: "10px 12px" }}>
                <div style={{ fontSize: 9, color: tone.text, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" }}>{entry.label}</div>
                <div className="fa-num" style={{ marginTop: 8, fontSize: 17, fontWeight: 800, color: "var(--fg-1)", fontFamily: "var(--font-mono)" }}>{entry.title}</div>
                <div style={{ marginTop: 6, fontSize: 10, color: "var(--fg-4)", lineHeight: 1.5 }}>{entry.detail}</div>
              </div>
            );
          })}
        </div>
        <div style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-lg)", background: "var(--bg-panel)", padding: "10px 12px" }}>
          <div style={{ fontSize: 9, color: CME_META_TEXT, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" }}>后端解释摘要</div>
          <div style={{ marginTop: 8, fontSize: 11, color: "var(--fg-3)", lineHeight: 1.7 }}>{primarySummary}</div>
        </div>
      </CMEOptionsSurface>
      <CMEOptionsSurface title="Risk / Trace Brief" bodyStyle={{ display: "grid", gap: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {analysis?.fact_review_status ? (
            <FAStatusPill tone={reviewStatusTone(analysis.fact_review_status)}>
              {reviewStatusLabel(analysis.fact_review_status)}
            </FAStatusPill>
          ) : null}
          <FAStatusPill tone={reportStatusTone(snapshot.data_source.status)}>{snapshot.data_source.status}</FAStatusPill>
          <FAStatusPill tone="neutral">{snapshot.data_source.product}</FAStatusPill>
        </div>
        <div style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", background: "var(--bg-panel)", padding: "9px 10px" }}>
          <div style={{ fontSize: 9, color: CME_META_TEXT, marginBottom: 5 }}>下一风险提示</div>
          <div style={{ fontSize: 11, color: "var(--fg-3)", lineHeight: 1.6 }}>{nextRisk}</div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
          <div style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", background: "var(--bg-panel)", padding: "8px 10px" }}>
            <div style={{ fontSize: 9, color: CME_META_TEXT }}>source refs</div>
            <div className="fa-num" style={{ marginTop: 4, fontSize: 14, color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{snapshot.source_trace.length}</div>
          </div>
          <div style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", background: "var(--bg-panel)", padding: "8px 10px" }}>
            <div style={{ fontSize: 9, color: CME_META_TEXT }}>pending review</div>
            <div className="fa-num" style={{ marginTop: 4, fontSize: 14, color: "var(--fg-1)", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{analysis?.pending_review_count ?? 0}</div>
          </div>
        </div>
      </CMEOptionsSurface>
    </div>
  );
}
