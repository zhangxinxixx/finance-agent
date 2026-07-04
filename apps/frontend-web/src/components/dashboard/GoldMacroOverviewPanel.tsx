import { ArrowRight, GitBranch, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatGoldNetBiasLabel,
  formatGoldPhaseLabel,
  formatTransmissionPathLabel,
  goldConflictTone,
  goldNetBiasTone,
  normalizeGoldMainlineId,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview, GoldMainlineRanking } from "@/types/gold-mainlines";

interface GoldMacroOverviewPanelProps {
  overview?: GoldMacroOverview | null;
}

function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

function scoreFormulaLabel(item: GoldMainlineRanking): string {
  const direction = item.direction_score ?? 0;
  const impact = item.impact_score ?? 1;
  const confidence = item.confidence_score ?? 1;
  const freshness = item.freshness_score ?? 1;
  return `${direction}/${impact}/${confidence}/${freshness}`;
}

function unique(items: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of items) {
    const normalized = (item || "").trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function collectVerificationItems(overview: GoldMacroOverview): string[] {
  return unique([
    ...(overview.driver_conflict?.verification_needed ?? []),
    ...overview.verification_matrix.map((item) => item.label || item.reason || item.required_source || null),
  ]).slice(0, 3);
}

function rankingMainlineId(item: GoldMainlineRanking): string | null {
  return normalizeGoldMainlineId(item.mainline_id ?? item.mainline);
}

export function GoldMacroOverviewPanel({ overview }: GoldMacroOverviewPanelProps) {
  if (!overview) {
    return (
      <section className="fa-card min-h-[178px]">
        <header className="fa-card-header !px-3 !py-2">
          <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] fa-important-bg" />
          <div className="min-w-0 flex-1">
            <div className="dashboard-cme-micro-label">黄金主线总览</div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              <FAStatusPill tone="warn" dot={false} className="whitespace-nowrap">
                未生成
              </FAStatusPill>
              <span className="truncate text-[12px] font-semibold text-[var(--fg-2)]">等待后端产物</span>
            </div>
          </div>
        </header>
        <div className="fa-card-body space-y-3" style={{ padding: "9px 12px" }}>
          <div className="rounded border px-2.5 py-2" style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}>
            <div className="mb-1.5 text-[10px] font-semibold text-[var(--fg-5)]">主线入口</div>
            <p className="text-[11px] leading-5 text-[var(--fg-3)]">
              当前黄金主线总览产物暂不可用；先保留右栏入口，用于快速进入三条专题链路。
            </p>
          </div>
          <div className="grid gap-1.5">
            {[
              { to: "/gold-mainlines", label: "黄金主线排序" },
              { to: "/rates-dollar", label: "利率与美元" },
              { to: "/oil-geopolitics", label: "石油与地缘" },
            ].map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className="inline-flex items-center justify-between gap-2 rounded-[var(--radius-md)] border px-2.5 py-1.5 text-[10px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-panel)] hover:text-[var(--fg-2)]"
                style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}
              >
                <span>{item.label}</span>
                <ArrowRight size={11} />
              </Link>
            ))}
          </div>
        </div>
      </section>
    );
  }

  const conflict = overview.driver_conflict;
  const topRankings = [...(overview.theme_rankings ?? [])]
    .sort((left, right) => left.rank - right.rank)
    .slice(0, 5);
  const verificationItems = collectVerificationItems(overview);
  const warOilRateChain = overview.war_oil_rate_chain;
  const riskScore = formatScore(overview.risk_score);

  return (
    <section className="fa-card min-h-[232px]">
      <header className="fa-card-header !px-3 !py-2">
        <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] fa-important-bg" />
        <div className="min-w-0 flex-1">
          <div className="dashboard-cme-micro-label">黄金主线总览</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2">
            <FAStatusPill tone={goldNetBiasTone(overview.net_bias)} dot={false} className="whitespace-nowrap">
              {formatGoldNetBiasLabel(overview.net_bias)}
            </FAStatusPill>
            <span className="truncate text-[12px] font-semibold text-[var(--fg-2)]">
              {formatGoldPhaseLabel(overview.phase)}
            </span>
            <span className="fa-num text-[10px] text-[var(--fa-text-label)]">{overview.as_of?.slice(0, 10) || "日期未知"}</span>
          </div>
        </div>
      </header>

      <div className="fa-card-body space-y-3" style={{ padding: "9px 12px" }}>
        <div className="rounded border px-2.5 py-2" style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}>
          <div className="flex items-center justify-between gap-2">
            <span className="dashboard-cme-micro-label">主导主线</span>
            <span className="fa-num text-[10px] text-[var(--fa-text-label)]">风险 {riskScore}/100</span>
          </div>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5">
            <FAStatusPill tone="info" dot={false}>
              {formatGoldMainlineLabel(overview.dominant_mainline)}
            </FAStatusPill>
            {conflict?.dominant_driver ? (
              <FAStatusPill tone={goldConflictTone(conflict.status)} dot={false}>
                {formatGoldDriverLabel(conflict.dominant_driver)}
              </FAStatusPill>
            ) : null}
          </div>
          <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-[var(--fg-3)]">
            {overview.one_line_conclusion || conflict?.explanation || "后端暂未返回主线结论。"}
          </p>
        </div>

        {topRankings.length ? (
          <div className="space-y-1.5">
            {topRankings.map((item) => (
              <div
                key={`${rankingMainlineId(item) ?? item.label ?? "mainline"}-${item.rank}`}
                className="grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-2 rounded border px-2.5 py-1.5"
                style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}
              >
                <span className="fa-num text-[10px] text-[var(--fg-5)]">#{item.rank}</span>
                <div className="min-w-0">
	                  <div className="truncate text-[11px] font-semibold text-[var(--fg-2)]">
	                    {item.label || formatGoldMainlineLabel(rankingMainlineId(item))}
	                  </div>
                  <div className="truncate text-[10px] text-[var(--fg-5)]">{formatGoldNetBiasLabel(item.direction)}</div>
                </div>
                <div className="text-right">
                  <div className="fa-num text-[11px] font-semibold text-[var(--fg-2)]">{formatScore(item.theme_score ?? item.score)}</div>
                  <div className="fa-num text-[8px] text-[var(--fg-5)]">D/I/C/F {scoreFormulaLabel(item)}</div>
                </div>
              </div>
            ))}
          </div>
        ) : null}

        {warOilRateChain ? (
          <div className="rounded border px-2.5 py-2" style={{ borderColor: "var(--warn-border)", background: "var(--warn-soft)" }}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-1.5 text-[10px] font-semibold text-[var(--warn)]">
                <GitBranch size={11} />
                <span className="truncate">{formatTransmissionPathLabel(warOilRateChain.path_id)}</span>
              </div>
              {warOilRateChain.conclusion_code ? (
                <FAStatusPill tone={goldNetBiasTone(warOilRateChain.net_effect)} dot={false} className="shrink-0 px-[5px] py-[1px] text-[9px]">
                  {warOilRateChain.conclusion_code}. {warOilRateChain.conclusion_label || formatGoldNetBiasLabel(warOilRateChain.net_effect)}
                </FAStatusPill>
              ) : null}
            </div>
            <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-[var(--fg-2)]">
              {warOilRateChain.summary}
            </p>
          </div>
        ) : null}

        <div className="rounded border px-2.5 py-2" style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}>
          <div className="mb-1.5 text-[10px] font-semibold text-[var(--fg-5)]">关键位</div>
          <div className="grid grid-cols-4 gap-1.5">
            {[
              { level: "3900", label: "风险线" },
              { level: "4000", label: "分水岭" },
              { level: "4100-4120", label: "修复确认" },
              { level: "4300", label: "趋势确认" },
            ].map((item) => (
              <div key={item.level} className="min-w-0 rounded border border-[var(--border-faint)] px-1.5 py-1 text-center">
                <div className="fa-num truncate text-[10px] font-semibold text-[var(--fg-2)]">{item.level}</div>
                <div className="mt-0.5 truncate text-[8px] text-[var(--fg-5)]">{item.label}</div>
              </div>
            ))}
          </div>
        </div>

        {verificationItems.length ? (
          <div className="rounded border px-2.5 py-2" style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}>
            <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold text-[var(--fg-5)]">
              <ShieldAlert size={11} />
              <span>待验证</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {verificationItems.map((item) => (
                <span key={item} className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-2 py-0.5 text-[10px] font-semibold text-[var(--fg-3)]">
                  {formatGoldDriverLabel(item)}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        <div className="flex justify-end">
          <Link
            to="/gold-mainlines"
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border px-2.5 py-1 text-[10px] font-semibold tracking-[0] text-[var(--fg-3)] transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-panel)] hover:text-[var(--fg-2)]"
            style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}
          >
            查看主线排序
            <ArrowRight size={11} />
          </Link>
        </div>
      </div>
    </section>
  );
}
