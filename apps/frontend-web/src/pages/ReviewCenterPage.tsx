import { useMemo, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { ReviewCenterFilterBar } from "@/components/review-center/ReviewCenterFilterBar";
import {
  ReviewCenterEmptyState,
  ReviewCenterErrorBanner,
  ReviewCenterLoadingState,
} from "@/components/review-center/ReviewCenterPageStates";
import {
  OrchestrationManualReviewCard,
  PromptEvolutionProposalCard,
  PromptEvolutionValidationCard,
  ReviewCard,
  ReviewCenterSummaryCard,
  SystemEvolutionProposalCard,
} from "@/components/review-center/ReviewCenterSections";
import type { FATabOption } from "@/components/shared/FATabBar";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAWorkspaceHeader } from "@/components/shared/FAWorkspaceHeader";
import {
  REVIEW_STATUS_OPTIONS,
  filterReviewItems,
  getReviewStatusLabel,
  listReviewModules,
} from "@/components/review-center/reviewCenterPageModel";
import { useReviewCenter } from "@/hooks/useReviewCenter";
import { usePromptEvolutionProposal } from "@/hooks/usePromptEvolutionProposal";
import { usePromptEvolutionReview } from "@/hooks/usePromptEvolutionReview";
import { useOrchestrationManualReview } from "@/hooks/useOrchestrationManualReview";
import { useSystemEvolutionReview } from "@/hooks/useSystemEvolutionReview";

const PROMPT_EVOLUTION_AGENT_OPTIONS = [
  { value: "event_attribution_agent", label: "EventAttribution" },
  { value: "transmission_chain_agent", label: "TransmissionChain" },
  { value: "driver_decomposition_agent", label: "DriverDecomposition" },
  { value: "mainline_ranking_agent", label: "MainlineRanking" },
  { value: "gold_macro_overview_agent", label: "GoldMacroOverview" },
  { value: "report_render_agent", label: "ReportRender" },
];

export function ReviewCenterPage() {
  const [status, setStatus] = useState<string>("pending");
  const [sourceModule, setSourceModule] = useState("");
  const [query, setQuery] = useState("");
  const [proposalAgentId, setProposalAgentId] = useState(PROMPT_EVOLUTION_AGENT_OPTIONS[0].value);
  const reviewCenter = useReviewCenter({ status: status === "all" ? undefined : status, sourceModule: sourceModule || undefined });
  const promptEvolution = usePromptEvolutionProposal(proposalAgentId, 10);
  const promptEvolutionReview = usePromptEvolutionReview();
  const orchestrationReview = useOrchestrationManualReview();
  const systemEvolution = useSystemEvolutionReview();

  const filteredReviews = useMemo(() => filterReviewItems(reviewCenter.reviews, query), [query, reviewCenter.reviews]);
  const modules = useMemo(() => listReviewModules(reviewCenter.reviews), [reviewCenter.reviews]);
  const statusTabs = useMemo(
    () => (["all", ...REVIEW_STATUS_OPTIONS] as const).map((value) => ({
      value,
      label: getReviewStatusLabel(value),
      count: value === "all" ? reviewCenter.reviews.length : reviewCenter.reviews.filter((item) => item.status === value).length,
    })) satisfies Array<FATabOption<string>>,
    [reviewCenter.reviews],
  );

  if (reviewCenter.isLoading && reviewCenter.reviews.length === 0) {
    return <ReviewCenterLoadingState />;
  }

  return (
    <FAPageScaffold
      toolbar={(
        <div className="fa-page-stack">
          <FAWorkspaceHeader
          className="review-workspace-header"
          icon={ShieldCheck}
          title="人工复核"
          tabs={statusTabs}
          value={status}
          onChange={setStatus}
          ariaLabel="复核状态切换"
          actions={(
            <button type="button" onClick={reviewCenter.refetch} className="fa-workspace-toolbar-button">
              <RefreshCw size={12} />
              刷新
            </button>
          )}
          primaryLabel="复核状态"
          primaryItems={[
            { label: "总数", value: reviewCenter.total },
            { label: "筛后", value: filteredReviews.length },
            { label: "状态", value: getReviewStatusLabel(status) },
          ]}
          secondaryLabel="范围"
          secondaryItems={[
            { label: "模块", value: sourceModule || "全部模块" },
            { label: "编排复核", value: orchestrationReview.count },
            { label: "系统演进", value: systemEvolution.proposalCount },
            { label: "Prompt验证", value: promptEvolutionReview.caseCount },
          ]}
        />

          <ReviewCenterFilterBar
          status={status}
          onStatusChange={setStatus}
          sourceModule={sourceModule}
          modules={modules}
          onSourceModuleChange={setSourceModule}
          query={query}
          onQueryChange={setQuery}
          onRefresh={reviewCenter.refetch}
          showStatusTabs={false}
          showRefresh={false}
        />
        </div>
      )}
      bodyClassName="fa-page-stack"
    >
      {reviewCenter.isError ? <ReviewCenterErrorBanner message={reviewCenter.error?.message ?? "无法加载 /api/reviews"} /> : null}
      {reviewCenter.actionError ? <ReviewCenterErrorBanner message={reviewCenter.actionError.message} /> : null}
      {orchestrationReview.isError ? <ReviewCenterErrorBanner message={orchestrationReview.error?.message ?? "无法加载 /api/orchestration/manual-review"} /> : null}
      {orchestrationReview.actionError ? <ReviewCenterErrorBanner message={orchestrationReview.actionError.message} /> : null}
      {systemEvolution.isError ? <ReviewCenterErrorBanner message={systemEvolution.error?.message ?? "无法加载 /api/governance/system-evolution/latest"} /> : null}
      {systemEvolution.actionError ? <ReviewCenterErrorBanner message={systemEvolution.actionError.message} /> : null}
      {promptEvolutionReview.isError ? <ReviewCenterErrorBanner message={promptEvolutionReview.error?.message ?? "无法加载 /api/governance/prompt-evolution/latest"} /> : null}
      {promptEvolutionReview.actionError ? <ReviewCenterErrorBanner message={promptEvolutionReview.actionError.message} /> : null}

      <ReviewCenterSummaryCard
        source={reviewCenter.source}
        total={reviewCenter.total}
        filteredCount={filteredReviews.length}
      />

      {orchestrationReview.items.length > 0 ? (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[12px] font-semibold text-[var(--fg-2)]">自动化编排复核</div>
              <div className="mt-1 text-[10px] text-[var(--fg-5)]">{orchestrationReview.tradeDate || "latest"} · {orchestrationReview.count} 项</div>
            </div>
            <button type="button" onClick={orchestrationReview.refetch} className="fa-workspace-toolbar-button">
              <RefreshCw size={12} />
              刷新编排
            </button>
          </div>
          {orchestrationReview.items.map((item) => (
            <OrchestrationManualReviewCard
              key={item.dedupe_key}
              item={item}
              onAction={orchestrationReview.submitAction}
              actionDedupeKey={orchestrationReview.actionDedupeKey}
            />
          ))}
        </section>
      ) : null}

      <SystemEvolutionProposalCard
        review={systemEvolution.review}
        isLoading={systemEvolution.isLoading}
        isError={systemEvolution.isError}
        errorMessage={systemEvolution.error?.message}
        actionProposalId={systemEvolution.actionProposalId}
        onProposalAction={systemEvolution.submitProposalAction}
        onRefresh={systemEvolution.refetch}
      />

      <PromptEvolutionProposalCard
        preview={promptEvolution.preview}
        selectedAgentId={proposalAgentId}
        agentOptions={PROMPT_EVOLUTION_AGENT_OPTIONS}
        isLoading={promptEvolution.isLoading}
        isError={promptEvolution.isError}
        errorMessage={promptEvolution.error?.message}
        onAgentChange={setProposalAgentId}
        onRefresh={promptEvolution.refetch}
      />

      <PromptEvolutionValidationCard
        review={promptEvolutionReview.review}
        isLoading={promptEvolutionReview.isLoading}
        isError={promptEvolutionReview.isError}
        errorMessage={promptEvolutionReview.error?.message}
        actionKind={promptEvolutionReview.actionKind}
        actionError={promptEvolutionReview.actionError}
        onReleaseAction={promptEvolutionReview.submitReleaseAction}
        onRefresh={promptEvolutionReview.refetch}
      />

      {filteredReviews.length > 0 ? (
        <div className="space-y-3">
          {filteredReviews.map((review) => (
            <ReviewCard
              key={review.review_id}
              review={review}
              onAction={reviewCenter.resolveReview}
              actionReviewId={reviewCenter.actionReviewId}
            />
          ))}
        </div>
      ) : (
        <ReviewCenterEmptyState />
      )}
    </FAPageScaffold>
  );
}

export default ReviewCenterPage;
