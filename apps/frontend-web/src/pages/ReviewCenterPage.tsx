import { useMemo, useState } from "react";
import { ReviewCenterFilterBar } from "@/components/review-center/ReviewCenterFilterBar";
import {
  ReviewCenterEmptyState,
  ReviewCenterErrorBanner,
  ReviewCenterLoadingState,
} from "@/components/review-center/ReviewCenterPageStates";
import { ReviewCard, ReviewCenterSummaryCard } from "@/components/review-center/ReviewCenterSections";
import { FAPageIntro } from "@/components/shared/FAPageIntro";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import {
  filterReviewItems,
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

  if (reviewCenter.isLoading && reviewCenter.reviews.length === 0) {
    return <ReviewCenterLoadingState />;
  }

  return (
    <FAPageScaffold
      intro={(
        <FAPageIntro
          eyebrow="人工复核"
          title="Review Center"
          description="把待处理 review 统一收敛到一页：上方筛选，中央摘要，底部列表，降低跨模块来回定位问题的成本。"
          meta={(
            <>
              <span className="text-[10px] text-[var(--fg-4)]">总数 {reviewCenter.total}</span>
              <span className="text-[10px] text-[var(--fg-4)]">筛后 {filteredReviews.length}</span>
              <span className="text-[10px] text-[var(--fg-4)]">状态 {status}</span>
            </>
          )}
        />
      )}
      toolbar={(
        <ReviewCenterFilterBar
          status={status}
          onStatusChange={setStatus}
          sourceModule={sourceModule}
          modules={modules}
          onSourceModuleChange={setSourceModule}
          query={query}
          onQueryChange={setQuery}
          onRefresh={reviewCenter.refetch}
        />
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
