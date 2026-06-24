import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { getStatusLabel } from "@/components/shared/statusMeta";
import type { DashboardSummary } from "@/types/dashboard";

import { formatOptionalNumber, getConfidenceColor, getWallBias, translateIntent } from "./CMEOptionsSummaryFormat";

interface CMEOptionsSummaryProps {
  options: DashboardSummary["cme_options"];
}

function SummaryTile({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div
      className="rounded border px-2.5 py-2"
      style={{
        borderColor: "var(--border-faint)",
        background: "var(--bg-card-inner)",
      }}
    >
      <div
        style={{
          fontSize: "7px",
          fontWeight: 600,
          letterSpacing: "0.06em",
          color: "var(--fg-5)",
          textTransform: "uppercase" as const,
        }}
      >
        {label}
      </div>
      <div className="fa-num" style={{ marginTop: "3px", fontSize: "12px", fontWeight: 700, color: "var(--fg-1)" }}>
        {value}
      </div>
    </div>
  );
}

function MainLevelRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | null;
  tone: "up" | "down";
}) {
  return (
    <div className="flex items-center justify-between gap-2 rounded border px-2.5 py-2" style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}>
      <div style={{ fontSize: "8px", fontWeight: 600, letterSpacing: "0.06em", color: "var(--fg-5)", textTransform: "uppercase" as const }}>{label}</div>
      <div className="fa-num" style={{ fontSize: "12px", fontWeight: 700, color: tone === "down" ? "var(--down)" : "var(--up)" }}>
        {formatOptionalNumber(value, 0)}
      </div>
    </div>
  );
}

function strongestWall(walls: DashboardSummary["cme_options"]["upper_resistance_walls"]): number | null {
  if (walls.length === 0) return null;
  return [...walls].sort((a, b) => b.score - a.score)[0]?.strike ?? null;
}

export function CMEOptionsSummary({ options }: CMEOptionsSummaryProps) {
  const confidenceScore = Math.max(0, Math.min(1, options.confidence?.score ?? options.intent_score ?? 0));
  const confidenceLevel = options.confidence?.level ?? "low";
  const confidenceColor = getConfidenceColor(confidenceLevel);
  const wallBias = getWallBias(options.wall_score);
  const dataStatus = options.data_status || options.confidence?.data_status || "UNAVAILABLE";
  const mainResistance = strongestWall(options.upper_resistance_walls);
  const mainSupport = strongestWall(options.lower_support_walls);
  const confidencePct = `${Math.round(confidenceScore * 100)}%`;
  const ageDays = options.confidence?.age_days;

  return (
    <div className="fa-card">
      <div className="fa-card-header">
        <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] bg-[var(--warn)]" />
        <div className="min-w-0 flex-1">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">CME 期权结构</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2">
            <span className="truncate" style={{ fontSize: "12px", fontWeight: 600, color: "var(--fg-2)" }}>
              {translateIntent(options.intent)}
            </span>
            <span style={{ fontSize: "9px", color: "var(--fg-5)" }}>{options.trade_date || "日期未知"}</span>
            <FAStatusPill tone="neutral" dot={false} className="whitespace-nowrap" title={wallBias.label}>
              <span style={{ color: wallBias.color }}>{wallBias.label}</span>
            </FAStatusPill>
            <FAStatusPill
              tone="neutral"
              dot={false}
              className="whitespace-nowrap"
              title={`置信度 ${confidencePct}`}
            >
              <span style={{ color: confidenceColor }}>置信 {confidencePct}</span>
            </FAStatusPill>
          </div>
        </div>
      </div>

      <div className="fa-card-body space-y-3" style={{ padding: "10px 12px" }}>
        <div className="grid grid-cols-2 gap-2">
          <SummaryTile label="Gamma Zero" value={formatOptionalNumber(options.gamma_zero, 1)} />
          <SummaryTile label="Pin" value={formatOptionalNumber(options.pin_level, 1)} />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <MainLevelRow label="主阻力" value={mainResistance} tone="down" />
          <MainLevelRow label="主支撑" value={mainSupport} tone="up" />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <FAStatusPill status={dataStatus} domain="source" dot={false} className="whitespace-nowrap">
            {getStatusLabel(dataStatus, "source")}
          </FAStatusPill>
          {typeof ageDays === "number" ? (
            <FAStatusPill tone="dim" dot={false} className="whitespace-nowrap">
              {`距今 ${ageDays} 天`}
            </FAStatusPill>
          ) : null}
        </div>

        <div className="flex justify-end">
          <Link
            to="/cme-options"
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border px-2.5 py-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-3)] transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-panel)] hover:text-[var(--fg-2)]"
            style={{
              borderColor: "var(--border-faint)",
              background: "var(--bg-card-inner)",
            }}
          >
            查看期权结构
            <ArrowRight size={11} />
          </Link>
        </div>
      </div>
    </div>
  );
}
