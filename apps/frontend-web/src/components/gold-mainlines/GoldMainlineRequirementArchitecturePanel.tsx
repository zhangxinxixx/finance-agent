import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatGoldPricingLayerLabel,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview, MainlineRequirement } from "@/types/gold-mainlines";

function readinessTone(value: string | null | undefined) {
  if (value === "ready") return "up";
  if (value === "partial") return "warn";
  if (value === "missing") return "down";
  return "neutral";
}

function readinessLabel(value: string | null | undefined): string {
  if (value === "ready") return "可分析";
  if (value === "partial") return "部分可分析";
  if (value === "missing") return "待开发";
  return value || "未知";
}

export function GoldMainlineRequirementArchitecturePanel({ overview }: { overview: GoldMacroOverview }) {
  const requirements = overview.mainline_requirements ?? [];
  if (!requirements.length) return null;

  const readiness = overview.analysis_readiness;
  const gaps = overview.architecture_gaps ?? readiness?.next_gaps ?? [];

  return (
    <FACard
      title="分析能力架构"
      eyebrow="First Principles"
      accent="info"
      className="shrink-0"
      action={readiness ? (
        <FAStatusPill tone={readinessTone(readiness.status)} dot={false}>
          {readinessLabel(readiness.status)} {readiness.ready_count}/{readiness.total_count}
        </FAStatusPill>
      ) : null}
    >
      <div className="grid gap-3">
        <div className="grid gap-1.5 sm:grid-cols-4">
          {[
            { label: "完整", value: readiness?.ready_count ?? 0 },
            { label: "部分", value: readiness?.partial_count ?? 0 },
            { label: "待开发", value: readiness?.missing_count ?? 0 },
            { label: "覆盖率", value: `${Math.round((readiness?.coverage_ratio ?? 0) * 100)}%` },
          ].map((item) => (
            <div key={item.label} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5">
              <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">{item.label}</div>
              <div className="fa-num mt-0.5 text-[length:var(--type-card-title)] font-semibold text-[var(--fg-2)]">{item.value}</div>
            </div>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] table-fixed text-left text-[length:var(--type-caption)]">
            <colgroup>
              <col className="w-[160px]" />
              <col className="w-[98px]" />
              <col />
              <col className="w-[210px]" />
              <col className="w-[210px]" />
            </colgroup>
            <thead className="border-b border-[var(--border-faint)] text-[var(--fg-5)]">
              <tr>
                <th className="px-2.5 py-2 font-semibold">主线</th>
                <th className="px-2.5 py-2 font-semibold">能力</th>
                <th className="px-2.5 py-2 font-semibold">第一性原理</th>
                <th className="px-2.5 py-2 font-semibold">必需输入</th>
                <th className="px-2.5 py-2 font-semibold">缺口字段</th>
              </tr>
            </thead>
            <tbody>
              {requirements.map((item: MainlineRequirement) => (
                <tr key={item.mainline_id} className="border-b border-[var(--border-faint)] last:border-0">
                  <td className="px-2.5 py-2">
                    <div className="font-semibold text-[var(--fg-2)]">{formatGoldMainlineLabel(item.mainline_id)}</div>
                    <div className="mt-0.5 text-[length:var(--type-caption)] text-[var(--fg-5)]">{formatGoldPricingLayerLabel(item.pricing_layer)}</div>
                  </td>
                  <td className="px-2.5 py-2">
                    <FAStatusPill tone={readinessTone(item.readiness_status)} dot={false}>{readinessLabel(item.readiness_status)}</FAStatusPill>
                  </td>
                  <td className="px-2.5 py-2 text-[var(--fg-3)]">
                    <div className="line-clamp-2 leading-5">{item.asset_principle}</div>
                    <div className="mt-1 truncate text-[length:var(--type-caption)] text-[var(--fg-5)]">{item.analysis_chain.slice(0, 5).join(" -> ")}</div>
                  </td>
                  <td className="px-2.5 py-2">
                    <div className="flex flex-wrap gap-1">
                      {item.required_sources.slice(0, 4).map((source) => (
                        <FAStatusPill key={source} tone={item.missing_sources.includes(source) ? "warn" : "up"} dot={false}>
                          {formatGoldDriverLabel(source)}
                        </FAStatusPill>
                      ))}
                    </div>
                  </td>
                  <td className="px-2.5 py-2 text-[var(--fg-4)]">
                    <div className="line-clamp-2 break-words leading-5">
                      {(item.missing_fields.length ? item.missing_fields : item.development_gaps).slice(0, 4).join(" / ") || "暂无"}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {gaps.length ? (
          <div className="grid gap-1.5">
            <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">下一批架构缺口</div>
            {gaps.slice(0, 5).map((gap) => (
              <div key={gap} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">
                {gap}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </FACard>
  );
}
