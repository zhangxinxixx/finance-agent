import { useState } from "react";
import { CheckCircle2, ExternalLink, FileSearch, Layers3, SearchCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { MarketOddsEvidenceDrawer } from "@/components/reports/MarketOddsEvidenceDrawer";
import type { MarketOddsEvidenceItemView, MarketOddsEvidenceViewModel, ReportDetailView } from "@/types/reports";

export function ReportMarketOddsMatrix({ data }: { data: ReportDetailView }) {
  const evidence = data.market_odds_evidence;
  if (!evidence) return null;
  return <MarketOddsMatrix evidence={evidence} />;
}

export function MarketOddsMatrix({ evidence, reportDetailPath }: { evidence: MarketOddsEvidenceViewModel; reportDetailPath?: string | null }) {
  const [selected, setSelected] = useState<MarketOddsEvidenceItemView | null>(null);
  const itemCount = evidence.groups.reduce((count, group) => count + group.items.length, 0);
  const reviewCount = evidence.evidence_items.filter((item) => item.extraction_status === "needs_review").length;
  const isAccepted = evidence.extraction_status === "accepted" && itemCount > 0 && reviewCount === 0;
  const dataDate = evidence.trade_date ?? evidence.as_of.slice(0, 10);
  const analysisContext = evidence.analysis_context;
  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)]">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border-faint)] px-3 py-2.5">
        <div className="mr-1 flex items-center gap-2">
          <Layers3 size={14} className="text-[var(--brand-hover)]" />
          <h2 className="fa-card-title">赔率事件矩阵</h2>
        </div>
        <FAStatusPill tone="warn" dot={false}>单源辅助证据</FAStatusPill>
        <FAStatusPill tone={isAccepted ? "up" : "warn"} dot={false}>
          {isAccepted ? "识别通过" : reviewCount > 0 ? `${reviewCount} 项待复核` : "证据待复核"}
        </FAStatusPill>
        <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-4)]">{itemCount} 项 · {evidence.panel_count} 面板</span>
        {reportDetailPath ? (
          <Link
            to={reportDetailPath}
            className="ml-auto inline-flex h-7 items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--border)] px-2.5 text-[length:var(--type-caption)] font-semibold text-[var(--brand-hover)] hover:bg-[var(--bg-hover)]"
          >
            查看原始报告
            <ExternalLink size={11} />
          </Link>
        ) : null}
      </div>
      <div className="grid grid-cols-2 gap-px border-b border-[var(--border-faint)] bg-[var(--border-faint)] md:grid-cols-4">
        {[
          ["数据日期", dataDate],
          ["事件分组", `${evidence.groups.length} 组`],
          ["赔率条目", `${itemCount} 项`],
          ["复核状态", isAccepted ? "全部通过" : reviewCount > 0 ? `${reviewCount} 项待复核` : "待补充锚点"],
        ].map(([label, value]) => (
          <div key={label} className="bg-[var(--bg-card-inner)] px-3 py-2">
            <div className="fa-compact-label text-[var(--fg-5)]">{label}</div>
            <div className="mt-0.5 fa-num text-[length:var(--type-subtitle)] font-semibold text-[var(--fg-1)]">{value}</div>
          </div>
        ))}
      </div>
      <p className="border-b border-[var(--border-faint)] px-3 py-2 fa-muted-text">
        {String(evidence.interpretation.notice ?? "外部赔率不独立决定策略方向。")}
      </p>
      {analysisContext ? (
        <div className="border-b border-[var(--border-faint)]">
          <div className="grid xl:grid-cols-2">
            <section className="border-b border-[var(--border-faint)] px-3 py-3 xl:border-b-0 xl:border-r">
              <div className="flex items-center gap-2">
                <SearchCheck size={14} className="text-[var(--brand-hover)]" />
                <h3 className="fa-card-title">赔率结构解读</h3>
                <FAStatusPill tone={analysisContext.quality_status === "accepted" ? "up" : "warn"} dot={false}>
                  {analysisContext.quality_status === "accepted" ? "分析已验收" : "确定性降级"}
                </FAStatusPill>
              </div>
              <p className="mt-2 fa-body-text">{analysisContext.structure_summary}</p>
            </section>
            <section className="px-3 py-3">
              <div className="flex items-center gap-2">
                <Sparkles size={14} className="text-[var(--warn)]" />
                <h3 className="fa-card-title">对黄金的辅助含义</h3>
              </div>
              <p className="mt-2 fa-body-text">{analysisContext.gold_implication}</p>
            </section>
          </div>
          <section className="border-t border-[var(--border-faint)] px-3 py-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 size={14} className="text-[var(--info)]" />
              <h3 className="fa-card-title">需要确认的变量</h3>
              <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-5)]">{analysisContext.confirmation_variables.length} 项</span>
            </div>
            <div className="mt-2 grid gap-x-5 gap-y-1.5 md:grid-cols-2">
              {analysisContext.confirmation_variables.map((item, index) => (
                <div key={`${index}:${item}`} className="flex items-start gap-2 text-[length:var(--type-body-sm)] leading-5 text-[var(--fg-3)]">
                  <span className="fa-num mt-0.5 shrink-0 text-[var(--fg-5)]">{String(index + 1).padStart(2, "0")}</span>
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      ) : null}
      {itemCount === 0 ? (
        <div className="border-b border-[var(--border-faint)] px-3 py-5 text-center">
          <p className="fa-card-title">暂无可展示的赔率条目</p>
          <p className="mt-1 fa-muted-text">当前报告尚未形成可追溯的 figure 锚点，保持待复核状态，不补造概率。</p>
        </div>
      ) : null}
      <div className="columns-1 gap-3 p-3 xl:columns-2">
        {evidence.groups.map((group) => (
          <section key={group.group_key} className="mb-3 inline-block w-full break-inside-avoid overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] align-top">
            <div className="flex items-center justify-between border-b border-[var(--border-faint)] px-2.5 py-2">
              <h3 className="fa-label font-semibold text-[var(--fg-2)]">{group.label}</h3>
              <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-5)]">{group.items.length} 项</span>
            </div>
            <div className="divide-y divide-[var(--border-faint)]">
              {group.items.map((item) => (
                <button key={item.item_id} type="button" onClick={() => setSelected(item)} className="group w-full px-2.5 py-2 text-left hover:bg-[var(--bg-hover)]">
                  <span className="flex items-start gap-3">
                    <span className="min-w-0 flex-1">
                      <span className="block text-[length:var(--type-body-sm)] font-medium text-[var(--fg-2)]">{item.outcome_label}</span>
                      <span className="mt-1 flex flex-wrap items-center gap-2 text-[length:var(--type-caption)] text-[var(--fg-5)]">
                        <span className="fa-num">截至 {item.horizon_end || "未标注"}</span>
                        {item.extraction_status === "needs_review" ? <span className="font-semibold text-[var(--warn)]">待复核</span> : <span>已识别</span>}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="fa-num text-[length:var(--type-kpi)] font-semibold text-[var(--fg-1)]">{(item.probability * 100).toFixed(0)}%</span>
                      <FileSearch size={13} className="text-[var(--fg-5)] group-hover:text-[var(--brand-hover)]" />
                    </span>
                  </span>
                  <span className="mt-1.5 block h-1 overflow-hidden rounded-[var(--radius-pill)] bg-[var(--bg-hover)]">
                    <span
                      className={`block h-full rounded-[var(--radius-pill)] ${item.extraction_status === "needs_review" ? "bg-[var(--warn)]" : "bg-[var(--brand)]"}`}
                      style={{ width: `${Math.max(2, Math.min(100, item.probability * 100))}%` }}
                    />
                  </span>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
      {evidence.internal_comparisons.length > 0 ? (
        <div className="border-t border-[var(--border-faint)] px-3 pb-3 pt-2">
          <div className="flex items-center gap-2">
            <h3 className="fa-label font-semibold text-[var(--fg-2)]">内部模型对照</h3>
            <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-5)]">{evidence.internal_comparisons.length} 项完全可比</span>
          </div>
          <div className="mt-1 divide-y divide-[var(--border-faint)]">
            {evidence.internal_comparisons.map((comparison) => (
              <div key={`${comparison.external_item_id ?? "external"}:${comparison.internal_event_id ?? "internal"}`} className="flex flex-wrap items-center gap-2 py-1.5 text-[length:var(--type-body-sm)]">
                <FAStatusPill tone={comparison.comparison_status === "supports" ? "up" : "warn"} dot={false}>
                  {comparison.comparison_status === "supports" ? "支持" : "冲突"}
                </FAStatusPill>
                <span className="fa-num text-[var(--fg-2)]">外部 {(comparison.external_probability * 100).toFixed(0)}%</span>
                <span className="fa-num text-[var(--fg-2)]">内部 {(comparison.internal_probability * 100).toFixed(0)}%</span>
                <span className="fa-num text-[var(--fg-4)]">差值 {(comparison.probability_gap * 100).toFixed(1)}pp</span>
                <span className="text-[var(--fg-5)]">禁止聚合</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <MarketOddsEvidenceDrawer item={selected} parserVersion={evidence.parser_version} schemaVersion={evidence.feature_schema_version} onClose={() => setSelected(null)} />
    </section>
  );
}
