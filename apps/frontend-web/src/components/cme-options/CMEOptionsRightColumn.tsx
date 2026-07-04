import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, shortId, translateEvidence } from "./cmeOptionsFormat";
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

function synthesisStatusLabel(status: string | null | undefined) {
  if (status === "success") return "通过";
  if (status === "needs_review") return "需复核";
  if (status === "failed") return "失败";
  return status ?? "未知";
}

function biasLabel(bias: string | null | undefined) {
  if (bias === "bullish") return "偏多";
  if (bias === "bearish") return "偏空";
  if (bias === "neutral") return "中性";
  if (bias === "mixed") return "多空交织";
  return bias || "中性";
}

function severityLabel(severity: string | null | undefined) {
  if (severity === "high") return "高";
  if (severity === "medium") return "中";
  if (severity === "low") return "低";
  return severity ?? "待定";
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

  const topMeta = [
    analysis?.fact_review_status ? (
      <FAStatusPill key="fact-review" tone={reviewStatusTone(analysis.fact_review_status)}>
        {reviewStatusLabel(analysis.fact_review_status)}
      </FAStatusPill>
    ) : null,
    synthesis?.synthesis_status ? (
      <FAStatusPill
        key="synthesis"
        tone={synthesis.synthesis_status === "success" ? "up" : synthesis.synthesis_status === "needs_review" ? "warn" : "info"}
      >
        综合 {synthesisStatusLabel(synthesis.synthesis_status)}
      </FAStatusPill>
    ) : null,
    cmeAgent ? <FAStatusPill key="bias" tone="neutral">{biasLabel(cmeAgent.bias)}</FAStatusPill> : null,
    analysis?.pending_review_count ? (
      <FAStatusPill key="pending" tone="warn">待复核 {analysis.pending_review_count}</FAStatusPill>
    ) : null,
  ].filter(Boolean);

  const compactMetaGrid = {
    display: "grid",
    gridTemplateColumns: "repeat(2,minmax(0,1fr))",
    gap: 6,
  } as const;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
      <CMEOptionsSurface title="后端解释" bodyStyle={{ display: "grid", gap: 8 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
          {topMeta}
        </div>
        <div style={{ fontSize: 11, color: "var(--fg-3)", lineHeight: 1.55 }}>{translateEvidence(primarySummary)}</div>
        <div style={compactMetaGrid}>
          <div style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", padding: "7px 9px", background: "var(--bg-panel)" }}>
            <div style={{ fontSize: 8, color: CME_META_TEXT, marginBottom: 3 }}>运行编号</div>
            <div className="fa-num" style={{ fontSize: "var(--text-10)", color: "var(--fg-2)" }}>{shortId(analysis?.run_id)}</div>
          </div>
          <div style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", padding: "7px 9px", background: "var(--bg-panel)" }}>
            <div style={{ fontSize: 8, color: CME_META_TEXT, marginBottom: 3 }}>快照编号</div>
            <div className="fa-num" style={{ fontSize: "var(--text-10)", color: "var(--fg-2)" }}>{shortId(analysis?.snapshot_id)}</div>
          </div>
        </div>
      </CMEOptionsSurface>

      <CMEOptionsSurface title="审查状态" bodyStyle={{ display: "grid", gap: 8 }}>
        <div style={{ display: "grid", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span style={{ fontSize: 9, color: CME_META_TEXT }}>事实审查</span>
            <FAStatusPill tone={reviewStatusTone(analysis?.fact_review_status)}>
              {reviewStatusLabel(analysis?.fact_review_status)}
            </FAStatusPill>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span style={{ fontSize: 9, color: CME_META_TEXT }}>待处理问题项</span>
            <span className="fa-num" style={{ fontSize: "var(--text-11)", color: "var(--fg-2)", fontWeight: 700 }}>
              {analysis?.pending_review_count ?? 0}
            </span>
          </div>
        </div>
        {factReview?.claim_reviews?.length ? (
          <div style={{ display: "grid", gap: 6 }}>
            {factReview.claim_reviews.slice(0, 2).map((item) => (
              <div key={`${item.claim_id}-${item.verdict}`} style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", padding: "7px 9px", background: "var(--bg-panel)" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                  <span className="fa-num" style={{ fontSize: "var(--text-9)", color: "var(--fg-2)" }}>{shortId(item.claim_id)}</span>
                  <FAStatusPill tone={reviewStatusTone(item.verdict)}>{reviewStatusLabel(item.verdict)}</FAStatusPill>
                </div>
                <div style={{ marginTop: 5, fontSize: 9.5, color: "var(--fg-4)", lineHeight: 1.45 }}>{translateEvidence(item.reason)}</div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: 9.5, color: "var(--fg-5)" }}>当前未返回逐条断言审查结果。</div>
        )}
      </CMEOptionsSurface>

      <CMEOptionsSurface title="综合要点" bodyStyle={{ display: "grid", gap: 6 }}>
        {keyPoints.length > 0 ? keyPoints.slice(0, 5).map((line) => (
          <div key={line} style={{ display: "flex", gap: 8 }}>
            <span style={{ color: CME_META_TEXT, flexShrink: 0 }}>•</span>
            <div style={{ fontSize: 10, color: "var(--fg-3)", lineHeight: 1.45 }}>{translateEvidence(line)}</div>
          </div>
        )) : (
          <div style={{ fontSize: 9.5, color: "var(--fg-5)" }}>当前未返回综合共识点。</div>
        )}
        {watchlist.length > 0 ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5, paddingTop: 2 }}>
            {watchlist.slice(0, 4).map((item) => (
              <span
                key={item}
                style={{
                  padding: "2px 6px",
                  borderRadius: 999,
                  border: "1px solid var(--border-faint)",
                  background: "var(--bg-panel)",
                  fontSize: 9,
                  color: "var(--fg-4)",
                }}
              >
                {item}
              </span>
            ))}
          </div>
        ) : null}
      </CMEOptionsSurface>

      <CMEOptionsSurface title="待复核与降权" bodyStyle={{ display: "grid", gap: 6 }}>
        {analysis?.pending_reviews?.length ? analysis.pending_reviews.slice(0, 2).map((item) => (
          <div key={item.review_id} style={{ border: "1px solid var(--border-faint)", borderRadius: "var(--radius-md)", padding: "7px 9px", background: "var(--bg-panel)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <span className="fa-num" style={{ fontSize: "var(--text-9)", color: "var(--fg-2)" }}>{shortId(item.claim_id || item.review_id)}</span>
              <FAStatusPill tone={severityTone(item.severity)}>{severityLabel(item.severity)}</FAStatusPill>
            </div>
            <div style={{ marginTop: 5, fontSize: 9.5, color: "var(--fg-4)", lineHeight: 1.45 }}>{translateEvidence(item.reason)}</div>
          </div>
        )) : null}
        {reviewNotes.length > 0 ? reviewNotes.slice(0, 3).map((line) => (
          <div key={line} style={{ display: "flex", gap: 8 }}>
            <span style={{ color: CME_META_TEXT, flexShrink: 0 }}>•</span>
            <div style={{ fontSize: 10, color: "var(--fg-3)", lineHeight: 1.45 }}>{translateEvidence(line)}</div>
          </div>
        )) : (
          <div style={{ fontSize: 9.5, color: "var(--fg-5)" }}>当前没有待复核或降权说明。</div>
        )}
      </CMEOptionsSurface>
    </div>
  );
}
