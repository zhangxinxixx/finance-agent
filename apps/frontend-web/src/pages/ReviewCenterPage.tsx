import { useMemo, useState } from "react";
import { ReviewCenterFilterBar } from "@/components/review-center/ReviewCenterFilterBar";
import {
  ReviewCenterEmptyState,
  ReviewCenterErrorBanner,
  ReviewCenterLoadingState,
} from "@/components/review-center/ReviewCenterPageStates";
import { ReviewCard, ReviewCenterSummaryCard } from "@/components/review-center/ReviewCenterSections";
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
    <div className="finance-page-shell">
      <div className="flex flex-col gap-4">
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
      </div>
    </div>
  );
}

export default ReviewCenterPage;
