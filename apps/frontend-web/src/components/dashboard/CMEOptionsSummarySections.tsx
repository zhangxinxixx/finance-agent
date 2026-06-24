import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

import type { WallLevel } from "@/types/dashboard";
import { getStatusLabel } from "@/components/shared/statusMeta";

function SummaryBox({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "info" | "warn";
}) {
  const styles =
    tone === "warn"
      ? {
          background: "rgba(245,158,11,0.06)",
          border: "1px solid rgba(245,158,11,0.18)",
          padding: "8px 10px",
        }
      : tone === "info"
        ? {
            background: "rgba(59,130,246,0.05)",
            border: "1px solid rgba(59,130,246,0.15)",
            padding: "6px 10px",
          }
        : {
            background: "var(--bg-card-inner)",
            border: "1px solid var(--border-faint)",
            padding: "6px 10px",
          };

  return (
    <div
      className="rounded"
      style={{
        ...styles,
        fontSize: "9px",
        color: "var(--fg-4)",
        lineHeight: 1.5,
      }}
    >
      {children}
    </div>
  );
}

export function CMEOptionsSummaryHeader({
  expiries,
  tradeDate,
  wallBias,
  confidencePct,
  confidenceColor,
}: {
  expiries: string[];
  tradeDate: string | null | undefined;
  wallBias: { label: string; color: string };
  confidencePct: string;
  confidenceColor: string;
}) {
  return (
    <div className="fa-card-header">
      <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] bg-[var(--warn)]" />
      <div className="min-w-0 flex-1">
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
          CME 期权结构摘要
        </div>
        <div className="mt-0.5 flex items-center gap-2">
          <span className="truncate" style={{ fontSize: "12px", fontWeight: 600, color: "var(--fg-2)" }}>
            {expiries.join(" + ") || "JUN26 + JUL26"}
          </span>
          <span style={{ fontSize: "9px", color: "var(--fg-5)" }}>{tradeDate || "日期未知"}</span>
          <span
            style={{
              padding: "1px 6px",
              borderRadius: "3px",
              background: `${wallBias.color}18`,
              border: `1px solid ${wallBias.color}40`,
              fontSize: "9px",
              fontWeight: 600,
              color: wallBias.color,
            }}
          >
            {wallBias.label}
          </span>
          <span
            style={{
              padding: "1px 6px",
              borderRadius: "3px",
              background: `${confidenceColor}18`,
              border: `1px solid ${confidenceColor}40`,
              fontSize: "9px",
              fontWeight: 600,
              color: confidenceColor,
            }}
          >
            置信度 {confidencePct}
          </span>
        </div>
      </div>
    </div>
  );
}

export function CMEOptionsSummaryTextBox({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "info" | "warn";
}) {
  return <SummaryBox tone={tone}>{children}</SummaryBox>;
}

export function CMEOptionsSummaryAlert({
  resistance,
  support,
}: {
  resistance: WallLevel[];
  support: WallLevel[];
}) {
  if (resistance.length === 0 || support.length === 0) return null;

  return (
    <div
      className="flex items-center gap-2 rounded"
      style={{
        padding: "6px 10px",
        background: "rgba(240,82,82,0.08)",
        border: "1px solid rgba(240,82,82,0.18)",
      }}
    >
      <AlertTriangle size={11} color="var(--down)" />
      <span style={{ fontSize: "9px", color: "var(--fg-3)" }}>
        阻力墙 {resistance[0]?.strike.toLocaleString("en-US")} / 支撑墙 {support[0]?.strike.toLocaleString("en-US")}
      </span>
    </div>
  );
}

export function CMEOptionsSummaryStatusBox({
  status,
  ageDays,
}: {
  status: string | undefined;
  ageDays: number | null | undefined;
}) {
  const statusLabel = status ? getStatusLabel(status, "source") : "不可用";

  return (
    <SummaryBox>
      数据状态 {statusLabel}
      {typeof ageDays === "number" ? ` · 距今 ${ageDays} 天` : ""}
    </SummaryBox>
  );
}

export function CMEOptionsSummaryConfidenceBox({ note }: { note: string }) {
  return <SummaryBox tone="info">{note}</SummaryBox>;
}

export function CMEOptionsSummaryFallback() {
  return (
    <SummaryBox tone="warn">
      当前仅展示真实可用的 CME 状态字段；墙位和 GEX 明细不足时不扩写推导摘要。
    </SummaryBox>
  );
}
