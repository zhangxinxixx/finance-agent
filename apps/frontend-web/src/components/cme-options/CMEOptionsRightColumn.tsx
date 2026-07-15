import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import type { CMEOptionsDecisionResponse, CMEOptionsResponse } from "@/types/cme-options";
import { shortId, summarizeDecision, translateDecisionText } from "./cmeOptionsFormat";
import { CMEOptionsSurface } from "./CMEOptionsSurface";

interface CMEOptionsRightColumnProps {
  snapshot: CMEOptionsResponse;
  decision?: CMEOptionsDecisionResponse | null;
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
  return translateDecisionText(status ?? "未知");
}

function biasLabel(bias: string | null | undefined) {
  if (bias === "bullish") return "偏多";
  if (bias === "bearish") return "偏空";
  if (bias === "neutral") return "中性";
  if (bias === "mixed") return "多空交织";
  return translateDecisionText(bias || "中性");
}

function severityLabel(severity: string | null | undefined) {
  if (severity === "high") return "高";
  if (severity === "medium") return "中";
  if (severity === "low") return "低";
  return translateDecisionText(severity ?? "待定");
}

export function CMEOptionsRightColumn({ snapshot, decision }: CMEOptionsRightColumnProps) {
  const analysis = snapshot.analysis;
  const cmeAgent = analysis?.cme_options_agent;
  const factReview = analysis?.fact_review;
  const synthesis = analysis?.synthesis;
  const agentSummary = synthesis?.summary || cmeAgent?.summary;
  const decisionSummary = summarizeDecision(decision);
  const primarySummary = agentSummary || decisionSummary || "综合分析暂不可用，请以当前结构数据和风险提示为准。";
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
    !agentSummary && decisionSummary ? (
      <FAStatusPill key="decision-summary" tone="info">决策模型摘要</FAStatusPill>
    ) : null,
  ].filter(Boolean);

  return (
    <div className="cme-options-insight-stack">
      <CMEOptionsSurface title={agentSummary ? "后端综合判断" : "决策数据摘要"} bodyClassName="cme-options-insight-body">
        <div className="cme-options-meta-pills">
          {topMeta}
        </div>
        <p className="cme-options-insight-copy">{translateDecisionText(primarySummary)}</p>
        <div className="cme-options-meta-grid">
          <div className="cme-options-meta-card">
            <span>运行编号</span>
            <strong className="fa-num">{shortId(analysis?.run_id)}</strong>
          </div>
          <div className="cme-options-meta-card">
            <span>快照编号</span>
            <strong className="fa-num">{shortId(analysis?.snapshot_id)}</strong>
          </div>
        </div>
      </CMEOptionsSurface>

      <CMEOptionsSurface title="审查状态" bodyClassName="cme-options-insight-body">
        <div className="cme-options-status-list">
          <div className="cme-options-status-line">
            <span>事实审查</span>
            <FAStatusPill tone={reviewStatusTone(analysis?.fact_review_status)}>
              {reviewStatusLabel(analysis?.fact_review_status)}
            </FAStatusPill>
          </div>
          <div className="cme-options-status-line">
            <span>待处理问题项</span>
            <strong className="fa-num">
              {analysis?.pending_review_count ?? 0}
            </strong>
          </div>
        </div>
        {factReview?.claim_reviews?.length ? (
          <div className="cme-options-insight-list">
            {factReview.claim_reviews.slice(0, 2).map((item) => (
              <div key={`${item.claim_id}-${item.verdict}`} className="cme-options-insight-item">
                <div className="cme-options-insight-item-header">
                  <span className="fa-num">{shortId(item.claim_id)}</span>
                  <FAStatusPill tone={reviewStatusTone(item.verdict)}>{reviewStatusLabel(item.verdict)}</FAStatusPill>
                </div>
                <p>{translateDecisionText(item.reason)}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="cme-options-empty-copy">当前未返回逐条断言审查结果。</p>
        )}
      </CMEOptionsSurface>

      <CMEOptionsSurface title="综合要点" bodyClassName="cme-options-insight-body">
        {keyPoints.length > 0 ? keyPoints.slice(0, 5).map((line) => (
          <div key={line} className="cme-options-bullet-row">
            <span>•</span>
            <p>{translateDecisionText(line)}</p>
          </div>
        )) : (
          <p className="cme-options-empty-copy">当前未返回综合共识点。</p>
        )}
        {watchlist.length > 0 ? (
          <div className="cme-options-watchlist">
            {watchlist.slice(0, 4).map((item) => (
              <span key={item}>{translateDecisionText(item)}</span>
            ))}
          </div>
        ) : null}
      </CMEOptionsSurface>

      <CMEOptionsSurface title="待复核与降权" bodyClassName="cme-options-insight-body">
        {analysis?.pending_reviews?.length ? analysis.pending_reviews.slice(0, 2).map((item) => (
          <div key={item.review_id} className="cme-options-insight-item">
            <div className="cme-options-insight-item-header">
              <span className="fa-num">{shortId(item.claim_id || item.review_id)}</span>
              <FAStatusPill tone={severityTone(item.severity)}>{severityLabel(item.severity)}</FAStatusPill>
            </div>
            <p>{translateDecisionText(item.reason)}</p>
          </div>
        )) : null}
        {reviewNotes.length > 0 ? reviewNotes.slice(0, 3).map((line) => (
          <div key={line} className="cme-options-bullet-row">
            <span>•</span>
            <p>{translateDecisionText(line)}</p>
          </div>
        )) : (
          <p className="cme-options-empty-copy">当前没有待复核或降权说明。</p>
        )}
      </CMEOptionsSurface>
    </div>
  );
}
