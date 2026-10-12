import { readerValue } from "@/lib/readerLabels";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
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
  if (value === "ready") return "能力已具备";
  if (value === "partial") return "能力部分具备";
  if (value === "missing") return "能力待开发";
  return "能力尚未说明";
}

export function GoldMainlineRequirementArchitecturePanel({ overview }: { overview: GoldMacroOverview }) {
  const requirements = overview.mainline_requirements ?? [];

  const readiness = overview.analysis_readiness;
  const gaps = [...new Set([...(overview.architecture_gaps ?? []), ...(readiness?.next_gaps ?? [])])];
  const incomplete = requirements.filter((item) => item.missing_sources.length || item.missing_fields.length || item.development_gaps.length);
  if (!requirements.length && !gaps.length && !readiness) return null;
  const count = (value: number | undefined) => typeof value === "number" && Number.isFinite(value) ? String(value) : "未提供";
  const coverage = typeof readiness?.coverage_ratio === "number" && Number.isFinite(readiness.coverage_ratio) ? `${Math.round(readiness.coverage_ratio * 100)}%` : "未提供";

  return (
    <FACard
      title="分析限制与待补证据"
      eyebrow="能力登记"
      accent="info"
      className="shrink-0"
      action={readiness ? (
        <FAStatusPill tone={readinessTone(readiness.status)} dot={false}>
          {readinessLabel(readiness.status)} {count(readiness.ready_count)}/{count(readiness.total_count)}
        </FAStatusPill>
      ) : null}
    >
      <div className="grid gap-3">
        <EvidenceRecordActions record={{requirements,readiness,gaps}} label="分析能力与缺口登记" />
        <p className="text-[length:var(--type-body-sm)] leading-5 text-[var(--fg-3)]">以下是后端登记的分析能力与输入缺口，不代表当前数据已经可用；当前判断仍以页面上方的数据源与验证状态为准。</p>
        {incomplete.map((item) => (
          <div key={item.mainline_id ?? item.label} className="text-[length:var(--type-body-sm)] leading-5 text-[var(--fg-3)]">
            <span className="font-semibold">{formatGoldMainlineLabel(item.mainline_id)}：</span>
            {item.missing_sources.length ? <p className="break-words">待补输入：{item.missing_sources.map(formatGoldDriverLabel).join("、")}</p> : null}
            {item.missing_fields.length ? <p className="break-words">待补内容：{item.missing_fields.map((value) => readerValue(value, "字段中文说明待补充")).join("、")}</p> : null}
            {item.development_gaps.map((gap) => <p key={gap} className="break-words">{readerValue(gap, "尚有能力缺口，中文说明待补充。")}</p>)}
          </div>
        ))}
        {gaps.length ? <div className="grid gap-1.5 text-[length:var(--type-body-sm)] leading-5 text-[var(--fg-3)]">
          <div className="font-semibold">后端登记的能力缺口</div>
          {gaps.map((gap) => <p key={gap} className="break-words">{readerValue(gap, "尚有能力缺口，中文说明待补充。")}</p>)}
        </div> : null}
        <details>
          <summary className="cursor-pointer text-[length:var(--type-body-sm)] font-semibold text-[var(--brand-hover)]">查看分析能力登记（{requirements.length} 条）</summary>
          <div className="mt-3 grid gap-3">
        <div className="grid gap-1.5 sm:grid-cols-4">
          {[
          { label: "能力已具备", value: count(readiness?.ready_count) },
          { label: "能力部分具备", value: count(readiness?.partial_count) },
          { label: "能力待开发", value: count(readiness?.missing_count) },
          { label: "能力登记率", value: coverage },
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
                    <div className="break-words leading-5">{readerValue(item.asset_principle, "影响解释的中文说明待补充")}</div>
                    <div className="mt-1 break-words text-[length:var(--type-caption)] text-[var(--fg-5)]">{item.analysis_chain.map((step) => readerValue(step, "传导步骤待说明")).join(" → ")}</div>
                  </td>
                  <td className="px-2.5 py-2">
                    <div className="flex flex-wrap gap-1">
                      {item.required_sources.map((source) => (
                        <FAStatusPill key={source} tone={item.missing_sources.includes(source) ? "warn" : "info"} dot={false}>
                          {item.missing_sources.includes(source) ? "缺失：" : "必需："}{formatGoldDriverLabel(source)}
                        </FAStatusPill>
                      ))}
                    </div>
                  </td>
                  <td className="px-2.5 py-2 text-[var(--fg-4)]">
                    <div className="break-words leading-5">
                      {[...item.missing_fields, ...item.development_gaps].map((value) => readerValue(value, "说明待补充")).join(" / ") || "暂无"}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
          </div>
        </details>
      </div>
    </FACard>
  );
}
