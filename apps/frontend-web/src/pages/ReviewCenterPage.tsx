import { useMemo, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { ReviewCenterFilterBar } from "@/components/review-center/ReviewCenterFilterBar";
import {
  ReviewCenterEmptyState,
  ReviewCenterErrorBanner,
  ReviewCenterLoadingState,
} from "@/components/review-center/ReviewCenterPageStates";
import { ReviewCard, ReviewCenterSummaryCard } from "@/components/review-center/ReviewCenterSections";
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

export function ReviewCenterPage() {
  const [status, setStatus] = useState<string>("pending");
  const [sourceModule, setSourceModule] = useState("");
  const [query, setQuery] = useState("");
  const reviewCenter = useReviewCenter({ status: status === "all" ? undefined : status, sourceModule: sourceModule || undefined });

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

      <ReviewCenterSummaryCard
        source={reviewCenter.source}
        total={reviewCenter.total}
        filteredCount={filteredReviews.length}
      />

      {filteredReviews.length > 0 ? (
        <div className="space-y-3">
          {filteredReviews.map((review) => <ReviewCard key={review.review_id} review={review} />)}
        </div>
      ) : (
        <ReviewCenterEmptyState />
      )}
    </FAPageScaffold>
  );
}

export default ReviewCenterPage;
