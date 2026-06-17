import type { TaskReviewViewModel } from "@/types/agent-task";

export const REVIEW_STATUS_OPTIONS = ["pending", "approved", "rejected", "rerun"] as const;

export function filterReviewItems(reviews: TaskReviewViewModel[], query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) return reviews;
  return reviews.filter((review) =>
    [
      review.review_id,
      review.run_id,
      review.source_module,
      review.source_step_id,
      review.agent_output_id,
      review.claim_id,
      review.severity,
      review.reason,
      review.suggested_action,
      ...review.impact_modules,
      ...review.impact_report_ids,
      ...review.source_refs.flatMap((source) => [
        source.source_ref,
        source.label,
        source.provider,
        source.artifact_path,
        source.endpoint,
        source.source_url,
      ]),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );
}

export function listReviewModules(reviews: TaskReviewViewModel[]) {
  return Array.from(new Set(reviews.map((review) => review.source_module))).sort();
}

export function getReviewStatusLabel(status: string) {
  if (status === "all") return "全部";
  if (status === "pending") return "待处理";
  if (status === "approved") return "已通过";
  if (status === "rejected") return "已驳回";
  return "重新运行";
}
