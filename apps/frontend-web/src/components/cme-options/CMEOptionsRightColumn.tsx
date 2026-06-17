import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, shortId } from "./cmeOptionsFormat";
import { CMEOptionsSurface } from "./CMEOptionsSurface";

interface CMEOptionsRightColumnProps {
  snapshot: CMEOptionsResponse;
}

function reviewStatusTone(status: string | null | undefined): FAStatusTone {
  return getStatusTone(status, "review");
}

function reviewStatusLabel(status: string | null | undefined): string {
  return getStatusLabel(status, "review");
}

function severityTone(severity: string | null | undefined): FAStatusTone {
  return getStatusTone(severity);
}

export function CMEOptionsRightColumn({ snapshot }: CMEOptionsRightColumnProps) {
  const analysis = snapshot.analysis;
  const cmeAgent = analysis?.cme_options_agent;
  const factReview = analysis?.fact_review;
  const synthesis = analysis?.synthesis;
  const primarySummary = synthesis?.summary || cmeAgent?.summary || "当前未返回后端解释摘要。";
  const keyPoints = synthesis?.consensus_points?.length
    ? synthesis.consensus_points
    : synthesis?.key_findings?.length
      ? synthesis.key_findings
      : cmeAgent?.key_findings ?? [];
  const reviewNotes = [
    ...(analysis?.pending_reviews.map((item) => item.reason) ?? []),
    ...(synthesis?.warnings?.map((item) => item.message) ?? []),
    ...(synthesis?.divergent_points ?? []),
    ...(synthesis?.invalid_conditions ?? []),
    ...(factReview?.risk_points ?? []),
  ].filter((item, index, array) => item && array.indexOf(item) === index);
  const watchlist = synthesis?.watchlist?.length ? synthesis.watchlist : cmeAgent?.watchlist ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, overflowY: "auto" }}>
      <CMEOptionsSurface title="后端解释" bodyStyle={{ padding: 14, display: "grid", gap: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {analysis?.fact_review_status ? (
            <FAStatusPill tone={reviewStatusTone(analysis.fact_review_status)}>
              {reviewStatusLabel(analysis.fact_review_status)}
            </FAStatusPill>
          ) : null}
          {synthesis?.synthesis_status ? (
            <FAStatusPill tone={synthesis.synthesis_status === "success" ? "up" : synthesis.synthesis_status === "needs_review" ? "warn" : "info"}>
              综合 {synthesis.synthesis_status}
            </FAStatusPill>
          ) : null}
          {cmeAgent ? <FAStatusPill tone="neutral">{cmeAgent.bias || "neutral"}</FAStatusPill> : null}
          {analysis?.pending_review_count ? (
            <FAStatusPill tone="warn">待复核 {analysis.pending_review_count}</FAStatusPill>
          ) : null}
        </div>
        <div style={{ fontSize: 11, color: "var(--fg-3)", lineHeight: 1.7 }}>{primarySummary}</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
          <div style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", padding: "8px 10px", background: "var(--bg-panel)" }}>
            <div style={{ fontSize: 9, color: CME_META_TEXT, marginBottom: 4 }}>run_id</div>
            <div className="fa-num" style={{ fontSize: 11, color: "var(--fg-2)", fontFamily: "var(--font-mono)" }}>{shortId(analysis?.run_id)}</div>
          </div>
          <div style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", padding: "8px 10px", background: "var(--bg-panel)" }}>
            <div style={{ fontSize: 9, color: CME_META_TEXT, marginBottom: 4 }}>snapshot_id</div>
            <div className="fa-num" style={{ fontSize: 11, color: "var(--fg-2)", fontFamily: "var(--font-mono)" }}>{shortId(analysis?.snapshot_id)}</div>
          </div>
        </div>
      </CMEOptionsSurface>

      <CMEOptionsSurface title="审查状态" bodyStyle={{ padding: 14, display: "grid", gap: 10 }}>
        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span style={{ fontSize: 10, color: CME_META_TEXT }}>事实审查</span>
            <FAStatusPill tone={reviewStatusTone(analysis?.fact_review_status)}>
              {reviewStatusLabel(analysis?.fact_review_status)}
            </FAStatusPill>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span style={{ fontSize: 10, color: CME_META_TEXT }}>待处理问题项</span>
            <span className="fa-num" style={{ fontSize: 12, color: "var(--fg-2)", fontFamily: "var(--font-mono)", fontWeight: 700 }}>
              {analysis?.pending_review_count ?? 0}
            </span>
          </div>
        </div>
        {factReview?.claim_reviews?.length ? (
          <div style={{ display: "grid", gap: 8 }}>
            {factReview.claim_reviews.slice(0, 3).map((item) => (
              <div key={`${item.claim_id}-${item.verdict}`} style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", padding: "8px 10px", background: "var(--bg-panel)" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <span className="fa-num" style={{ fontSize: 10, color: "var(--fg-2)", fontFamily: "var(--font-mono)" }}>{shortId(item.claim_id)}</span>
                  <FAStatusPill tone={reviewStatusTone(item.verdict)}>{item.verdict}</FAStatusPill>
                </div>
                <div style={{ marginTop: 6, fontSize: 10, color: "var(--fg-4)", lineHeight: 1.55 }}>{item.reason}</div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: 10, color: "var(--fg-5)" }}>当前未返回逐条 claim 审查结果。</div>
        )}
      </CMEOptionsSurface>

      <CMEOptionsSurface title="综合要点" bodyStyle={{ padding: 14, display: "grid", gap: 8 }}>
        {keyPoints.length > 0 ? keyPoints.slice(0, 5).map((line) => (
          <div key={line} style={{ display: "flex", gap: 8 }}>
            <span style={{ color: CME_META_TEXT, flexShrink: 0 }}>•</span>
            <div style={{ fontSize: 11, color: "var(--fg-3)", lineHeight: 1.6 }}>{line}</div>
          </div>
        )) : (
          <div style={{ fontSize: 10, color: "var(--fg-5)" }}>当前未返回综合共识点。</div>
        )}
        {watchlist.length > 0 ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, paddingTop: 4 }}>
            {watchlist.slice(0, 6).map((item) => (
              <span
                key={item}
                style={{
                  padding: "3px 7px",
                  borderRadius: 999,
                  border: "1px solid var(--border-faint)",
                  background: "var(--bg-panel)",
                  fontSize: 10,
                  color: "var(--fg-4)",
                }}
              >
                {item}
              </span>
            ))}
          </div>
        ) : null}
      </CMEOptionsSurface>

      <CMEOptionsSurface title="待复核与降权" bodyStyle={{ padding: 14, display: "grid", gap: 8 }}>
        {analysis?.pending_reviews?.length ? analysis.pending_reviews.slice(0, 4).map((item) => (
          <div key={item.review_id} style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", padding: "8px 10px", background: "var(--bg-panel)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <span className="fa-num" style={{ fontSize: 10, color: "var(--fg-2)", fontFamily: "var(--font-mono)" }}>{shortId(item.claim_id || item.review_id)}</span>
              <FAStatusPill tone={severityTone(item.severity)}>{item.severity}</FAStatusPill>
            </div>
            <div style={{ marginTop: 6, fontSize: 10, color: "var(--fg-4)", lineHeight: 1.6 }}>{item.reason}</div>
          </div>
        )) : null}
        {reviewNotes.length > 0 ? reviewNotes.slice(0, 5).map((line) => (
          <div key={line} style={{ display: "flex", gap: 8 }}>
            <span style={{ color: CME_META_TEXT, flexShrink: 0 }}>•</span>
            <div style={{ fontSize: 11, color: "var(--fg-3)", lineHeight: 1.6 }}>{line}</div>
          </div>
        )) : (
          <div style={{ fontSize: 10, color: "var(--fg-5)" }}>当前没有待复核或降权说明。</div>
        )}
      </CMEOptionsSurface>
    </div>
  );
}
