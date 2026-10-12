import { ArrowLeft, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import {
  compareStrategySourceIdentity,
  type StrategyNavigationState,
} from "./strategyNavigation";
export {
  buildDashboardStrategyNavigationState,
  buildMinimalStrategyNavigationState,
  compareStrategySourceIdentity,
  readStrategyNavigationState,
} from "./strategyNavigation";
export type {
  StrategyNavigationState,
  StrategyReturnTarget,
  StrategySourceContext,
} from "./strategyNavigation";

const authorityLabels: Record<string, string> = {
  observation_only: "研究观察（未迁移）",
  accepted: "已接受",
  verified: "已核验",
  unavailable: "不可用",
  invalid: "无效",
  held: "沿用中",
};

function authorityLabel(value: string | null): string {
  if (!value) return "未提供";
  return authorityLabels[value] ?? "未识别";
}

export function StrategySourceNotice({
  navigation,
  currentIdentity,
}: {
  navigation: StrategyNavigationState;
  currentIdentity?: import("@/types/result-identity").ResultIdentity | null;
}) {
  const { strategySource: source } = navigation;
  const comparison = compareStrategySourceIdentity(source, currentIdentity);
  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2.5" aria-label="策略来源与当前结果">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="fa-section-title">来源与当前策略</span>
            <FAStatusPill tone={comparison.tone} dot={false}>{comparison.label}</FAStatusPill>
          </div>
          <p className="mt-1 text-[length:var(--type-body-sm)] leading-5 text-[var(--fg-3)]">
            {source.label} · 结果日期 {source.tradeDate ?? "未提供"} · {comparison.detail}
          </p>
        </div>
        <Link
          to={source.returnTo}
          state={navigation.dashboardResult ? { dashboardResult: navigation.dashboardResult } : undefined}
          className="inline-flex shrink-0 items-center gap-1 rounded-[var(--radius-sm)] border border-[var(--border)] px-2 py-1 text-[11px] font-semibold text-[var(--info)] hover:bg-[var(--bg-hover)]"
        >
          <ArrowLeft size={12} aria-hidden="true" />
          {source.returnLabel}
        </Link>
      </div>
      <div className="mt-2 grid gap-1 text-[length:var(--type-caption)] text-[var(--fg-4)] sm:grid-cols-3">
        <span>来源类型：<b className="text-[var(--fg-2)]">{source.label}</b></span>
        <span>研究时点：<b className="fa-num text-[var(--fg-2)]">{source.tradeDate ?? "未提供"}</b></span>
          <span>权威状态：<b className="text-[var(--fg-2)]">{authorityLabel(source.authority)}</b> · 发布资格 <b className="text-[var(--fg-2)]">{source.publishAllowed === null ? "未提供" : source.publishAllowed ? "允许" : "不允许"}</b></span>
      </div>
      <details className="mt-2 border-t border-[var(--border-faint)] pt-1.5">
        <summary className="cursor-pointer list-none text-[length:var(--type-caption)] text-[var(--fg-5)]">来源证据与身份字段</summary>
        <div className="mt-1 text-[length:var(--type-caption)] text-[var(--fg-4)]">
          <p>身份字段已保留用于核对；页面不展开内部标识。</p>
          <div className="mt-2"><EvidenceRecordActions label="脱敏来源身份记录" record={{ run_id: source.runId, snapshot_id: source.snapshotId, report_id: source.reportId, as_of: source.asOf, authority: source.authority, source_refs: source.sourceRefs }} /></div>
        </div>
      </details>
    </section>
  );
}

export function StrategyEvaluationScopeNotice({
  evaluationDate,
  currentStrategyDate,
}: {
  evaluationDate: string | null | undefined;
  currentStrategyDate: string | null | undefined;
}) {
  return (
    <section className="flex items-start gap-2 rounded-[var(--radius-lg)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2.5 text-[length:var(--type-body-sm)]" role="note" aria-label="影子评估范围">
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warn)]" aria-hidden="true" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <strong className="text-[var(--warn)]">影子评估范围</strong>
          <FAStatusPill tone="warn" dot={false}>策略身份无法核验</FAStatusPill>
        </div>
        <p className="mt-1 leading-5 text-[var(--fg-3)]">
          评估分区日期：{evaluationDate ?? "未提供"}；当前正式策略卡日期：{currentStrategyDate ?? "未提供"}。评估接口未返回对应的策略运行、数据快照或正式结果身份，以下表现不能直接称为当前策略表现。
        </p>
      </div>
    </section>
  );
}
