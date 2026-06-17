// ── SourceNode Component ──────────────────────────────────────
// 数据源 DAG 节点：source_name + domain 徽章 + status 状态灯 + provider_role

import { memo } from "react";
import type { DagNodeSpec } from "@/types/pipeline-dag";
import { DOMAIN_COLORS, providerRoleLabel } from "@/adapters/data-lineage";

const STATUS_STYLE: Record<string, { dot: string; text: string; bg: string; label: string }> = {
  success:  { dot: "var(--up)",   text: "var(--up)",   bg: "var(--color-up-subtle)",   label: "在线" },
  partial:  { dot: "#f59e0b",     text: "#d97706",     bg: "#fef3c7",                  label: "部分" },
  failed:   { dot: "var(--down)", text: "var(--down)", bg: "var(--color-down-subtle)",  label: "异常" },
  pending:  { dot: "var(--fg-5)", text: "var(--fg-4)", bg: "var(--bg-card-inner)",      label: "未接" },
};

const ROLE_BADGE_COLORS: Record<string, { bg: string; text: string }> = {
  主源: { bg: "#dbeafe", text: "#1d4ed8" },
  备用: { bg: "#fef3c7", text: "#92400e" },
  补充: { bg: "#e0e7ff", text: "#4338ca" },
  衍生: { bg: "#d1fae5", text: "#065f46" },
  聚合: { bg: "#fce7f3", text: "#9d174d" },
  候选: { bg: "#f3f4f6", text: "#374151" },
};

export const SourceNode = memo(function SourceNode({ data }: { data: any }) {
  const spec: DagNodeSpec = data.node_spec;
  const domain = spec.sub_type;
  const domainColor = DOMAIN_COLORS[domain] || "#94a3b8";
  const st = STATUS_STYLE[spec.status] || STATUS_STYLE.pending;
  const isGroup = spec.node_id.startsWith("grp::");

  // For group nodes: show aggregate info
  const totalCount = spec.output.fields?.total as number | undefined;
  const onlineCount = spec.output.fields?.online as number | undefined;
  const sourceKeys = spec.input.fields?.source_keys as string[] | undefined;

  // For individual source nodes: show role
  const providerRole = (spec.input.fields?.provider_role as string) || "derived";
  const roleLabel = providerRoleLabel(providerRole);
  const roleBadge = ROLE_BADGE_COLORS[roleLabel] || ROLE_BADGE_COLORS["候选"];

  const stalenessDays = spec.output.fields?.staleness_days as number | null | undefined;
  const downstreamStatus = spec.output.fields?.downstream_status as string | undefined;

  const hl = data.highlighted as string | undefined;
  const borderHl = hl === "selected"
    ? `0 0 0 2px var(--brand-gold), inset 0 0 0 1px var(--brand-gold)`
    : hl === "upstream" || hl === "downstream"
    ? "0 0 0 1px var(--brand-gold)/30"
    : "none";

  return (
    <div
      className="rounded-lg border shadow-sm cursor-pointer transition-all duration-200 hover:scale-[1.02]"
      style={{
        background: "var(--bg-card)",
        borderColor: `${domainColor}40`,
        borderLeftWidth: 4,
        borderLeftColor: domainColor,
        minWidth: 170,
        maxWidth: 220,
        boxShadow: borderHl,
      }}
    >
      {/* Top: Status + Label */}
      <div className="flex items-center gap-2 px-3 pt-2.5">
        <div className="relative shrink-0">
          <div className="w-2.5 h-2.5 rounded-full" style={{ background: st.dot }} />
          {spec.status === "running" && (
            <div className="absolute inset-0 rounded-full animate-ping opacity-40" style={{ background: st.dot }} />
          )}
        </div>
        <span className="text-[10px] font-bold text-[var(--fg-2)] truncate flex-1 leading-tight">
          {spec.label}
        </span>
      </div>

      {/* Middle: Domain badge + Role/Count badge */}
      <div className="flex items-center gap-1.5 px-3 pt-1.5 text-[8px]">
        <span
          className="rounded-sm px-1 py-px font-semibold"
          style={{ background: `${domainColor}15`, color: domainColor }}
        >
          {domain}
        </span>
        {isGroup ? (
          <span className="rounded-sm px-1 py-px font-semibold bg-[var(--bg-card-inner)] text-[var(--fg-3)]">
            {onlineCount}/{totalCount} 在线
          </span>
        ) : (
          <span
            className="rounded-sm px-1 py-px font-semibold"
            style={{ background: roleBadge.bg, color: roleBadge.text }}
          >
            {roleLabel}
          </span>
        )}
        {!isGroup && stalenessDays != null && stalenessDays > 0 && (
          <span className="ml-auto font-mono text-[var(--fg-5)] tabular-nums">
            {stalenessDays}d
          </span>
        )}
      </div>

      {/* Bottom: Status bar */}
      <div className="px-3 pb-2.5 pt-1.5">
        <div className="flex items-center gap-1.5">
          <div
            className="flex-1 h-1 rounded-full overflow-hidden"
            style={{ background: "var(--bg-card-inner)" }}
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: spec.status === "success" ? "100%"
                     : spec.status === "partial" ? "50%"
                     : spec.status === "failed" ? "100%"
                     : "15%",
                background: spec.status === "failed" ? "var(--down)"
                          : spec.status === "success" ? "var(--up)"
                          : spec.status === "partial" ? "#f59e0b"
                          : "var(--fg-5)",
              }}
            />
          </div>
          <span className="text-[7px] font-semibold shrink-0" style={{ color: st.text }}>
            {st.label}
          </span>
        </div>
        {downstreamStatus && downstreamStatus !== "READY" && (
          <div className="mt-1 text-[7px] text-[var(--fg-5)]">
            下游: {downstreamStatus === "DEGRADED" ? "降级" : "阻塞"}
          </div>
        )}
      </div>
    </div>
  );
});

export default SourceNode;
