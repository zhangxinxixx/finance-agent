import { EvidenceRecordActions } from "./EvidenceRecordActions";
import { ResearchDetails } from "./ResearchDetails";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import {
  isKnownResultIdentity,
  type ResultIdentity,
  type ResultIdentityEffectiveBaseline,
  type ResultIdentitySubject,
} from "@/types/result-identity";

interface ResultIdentityBarProps {
  identity?: ResultIdentity | null;
  subjectLabel?: string;
  baselineLabel?: string;
  className?: string;
}

const subjectFieldLabels: Record<keyof ResultIdentitySubject, string> = {
  kind: "结果类型",
  run_id: "运行 ID",
  premarket_snapshot_id: "盘前快照 ID",
  feature_snapshot_id: "特征快照 ID",
  result_id: "结果 ID",
  state_id: "状态 ID",
  strategy_id: "策略 ID",
  receipt_id: "收据 ID",
  bundle_ref: "产物包引用",
  verification_status: "核验状态",
  reason_code: "原因代码",
};

const relationshipLabels: Record<string, { label: string; tone: FAStatusTone }> = {
  same_effective_head: { label: "同一有效基线", tone: "up" },
  different_result: { label: "不同结果", tone: "warn" },
  unverified: { label: "无法核验", tone: "warn" },
  unavailable: { label: "当前基线不可用", tone: "dim" },
};

const verificationLabels: Record<string, string> = {
  verified: "已核验",
  unverified: "未核验",
  unavailable: "不可用",
  invalid: "无效",
  accepted: "已接受",
  degraded: "降级",
  held: "沿用中",
  valid: "有效",
  NO_TRADE: "不交易",
  no_trade: "不交易",
  needs_verification: "待核验",
};

const reasonLabels: Record<string, string> = {
  gold_daily_close_prebootstrap_hold: "尚未建立首个可核验的 黄金日结基线",
  gold_direction_authority_invalid: "黄金日结方向基线校验未通过",
  gold_strategy_status_not_directional: "黄金日结未给出可用方向",
  gold_report_bundle_verified: "报告包及登记身份已核验",
  gold_effective_head_unavailable: "尚无可用正式基准",
  gold_live_baseline_same_effective_head: "当前策略基准与有效研究结果一致",
  gold_result_identity_same_effective_head: "正式结果与有效基线属于同一次研究结果",
  gold_result_identity_different_result: "正式结果与有效基线不同",
  gold_legacy_mainline_unverified: "旧黄金主线结果尚未核验",
  gold_mainline_run_id_unavailable: "黄金主线记录不完整",
  gold_mainline_artifact_unavailable: "黄金主线产物不可用",
  gold_report_identity_mismatch: "报告身份不匹配",
  gold_report_registry_receipt_mismatch: "报告登记核验不一致",
  gold_report_bundle_verification_failed: "报告包核验失败",
  missing_result_identity: "后端没有返回参考资格核验",
  result_identity_schema_unknown: "参考资格核验信息格式无法识别",
};

function valueLabel(value: string | null | undefined): string {
  return value?.trim() || "未提供";
}

function statusLabel(value: string | null | undefined): string {
  return value ? verificationLabels[value] ?? "待确认" : "未提供";
}

function reasonLabel(value: string | null | undefined): string {
  if (!value) return "未提供";
  const label = reasonLabels[value];
  return label ?? "存在尚未解释的限制，参考资格仍待确认";
}

function fieldRows(subject: ResultIdentitySubject): Array<[string, string]> {
  return (Object.keys(subjectFieldLabels) as Array<keyof ResultIdentitySubject>).map((field) => [
    subjectFieldLabels[field],
    valueLabel(subject[field]),
  ]);
}

function ResultFieldGrid({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <div className="fa-label text-[var(--fg-5)]">{label}</div>
          <div className="mt-0.5 break-all fa-num text-[length:var(--type-caption)] text-[var(--fg-2)]">{value}</div>
        </div>
      ))}
    </div>
  );
}

function baselineRows(baseline: ResultIdentityEffectiveBaseline): Array<[string, string]> {
  return [
    ...fieldRows(baseline).map(([label, value]): [string, string] => [
      label === "收据 ID" ? "最新选头收据 ID" : label === "运行 ID" ? "有效产物运行 ID" : label,
      value,
    ]),
    ["基线状态", valueLabel(baseline.status)],
    ["HOLD 沿用", baseline.held ? "是（沿用）" : "否"],
    ["方向判断可用", baseline.authority_ready ? "是" : "否"],
    ["质量状态", valueLabel(baseline.quality_status)],
    ["策略状态", valueLabel(baseline.strategy_status)],
    ["选头决策时间", valueLabel(baseline.decision_as_of)],
  ];
}

function relationshipRows(identity: ResultIdentity): Array<[string, string]> {
  return [
    ["身份关系", valueLabel(identity.relationship.status)],
    ["关系原因代码", valueLabel(identity.relationship.reason_code)],
  ];
}

function identityState(identity: ResultIdentity | null | undefined): {
  label: string;
  tone: FAStatusTone;
  description: string;
} {
  if (!identity) {
    return {
      label: "无法核验",
      tone: "warn",
      description: "后端未提供参考资格核验，无法判断当前结果是否对应同一有效基线。",
    };
  }
  if (!isKnownResultIdentity(identity)) {
    return {
      label: "无法核验",
      tone: "warn",
      description: "结果核验信息不完整，暂不能确认与当前有效判断一致。",
    };
  }
  const relationship = relationshipLabels[identity.relationship.status] ?? relationshipLabels.unavailable;
  return {
    label: relationship.label,
    tone: relationship.tone,
    description: identity.relationship.reason_code
      ? reasonLabel(identity.relationship.reason_code)
      : identity.relationship.status === "same_effective_head"
        ? "后端已确认当前结果与有效基线属于同一次研究结果。"
        : identity.relationship.status === "different_result"
          ? "当前结果与有效基线不是同一次研究结果。"
          : "后端未确认当前结果与有效基线的关系。",
  };
}

export function ResultIdentityBar({
  identity,
  subjectLabel = "当前结果",
  baselineLabel = "当前有效基线",
  className = "",
}: ResultIdentityBarProps) {
  const state = identityState(identity);
  const known = isKnownResultIdentity(identity);
  const subject = known ? identity?.subject ?? null : null;
  const baseline = known ? identity?.effective_baseline ?? null : null;
  const subjectReason = known ? reasonLabel(subject?.reason_code) : "无法核验";
  const baselineReason = baseline
    ? reasonLabel(baseline.reason_code)
    : known
      ? "后端未提供当前有效基线。"
      : "无法核验当前有效基线。";

  return (
    <section
      aria-label="参考资格核验"
      className={`rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2.5 ${className}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="fa-section-title">参考资格核验</span>
            <FAStatusPill tone={state.tone} dot={false}>{state.label}</FAStatusPill>
          </div>
          <p className="mt-1 text-[length:var(--type-body-sm)] leading-5 text-[var(--fg-3)]">{state.description}</p>
        </div>
      </div>

      <div className="mt-1 flex flex-wrap gap-2 text-[length:var(--type-caption)] text-[var(--fg-4)]">
        <span>{subjectLabel}：{known ? statusLabel(subject?.verification_status) : "未核验"}</span>
        <span>{baseline?.authority_ready ? "方向判断可用" : "方向判断不可用"}</span>
        {baseline?.held ? <span>沿用既有判断，尚未形成新判断</span> : null}
      </div>
      <ResearchDetails label="查看核验记录" className="mt-2 border-t border-[var(--border-faint)] pt-2">
        <p className="leading-5">{subjectLabel}：{subjectReason}</p>
        <p className="leading-5">{baselineLabel}：{baselineReason}</p>
        <EvidenceRecordActions record={identity} label="本次结果与有效基准的核验记录" />
      </ResearchDetails>
    </section>
  );
}

export function LegacyStrategyIdentityNotice({ className = "" }: { className?: string }) {
  return (
    <div className={`rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)] ${className}`}>
      本页展示独立研究卡或历史审计记录，尚未与正式 黄金有效基线完成身份核验；不作为当前策略资格依据。
    </div>
  );
}
