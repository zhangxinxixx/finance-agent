import { GitBranch, ShieldAlert } from "lucide-react";

import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  GOLD_MAINLINE_META,
  formatGoldConflictStatusLabel,
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatGoldNarrativeText,
  formatGoldNetBiasLabel,
  formatGoldPricingLayerLabel,
  formatGoldVerificationReasonLabel,
  formatGoldVerificationStatusLabel,
  formatTransmissionPathLabel,
  goldConflictTone,
  goldNetBiasTone,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview, VerificationItem } from "@/types/gold-mainlines";
import {
  statusTone,
  type MainlineCoverageRow,
} from "./goldMainlineCoverage";

interface MainlineDetailDrawerProps {
  overview: GoldMacroOverview;
  rows: MainlineCoverageRow[];
}

function verificationLabel(item: VerificationItem): string {
  return formatGoldVerificationReasonLabel(item.label || item.reason || item.required_source || item.id);
}

function MissingCoveragePanel({ rows }: { rows: MainlineCoverageRow[] }) {
  const missingRows = rows.filter((row) => row.status === "missing");
  const pendingRows = rows.filter((row) => row.status === "pending");

  return (
    <FACard title="覆盖缺口" eyebrow="Coverage Gaps" accent="warn" className="shrink-0">
      <div className="grid gap-3">
        <div>
          <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">未覆盖主线</div>
          {missingRows.length ? (
            <div className="mt-1.5 grid gap-2">
              {missingRows.map((row) => {
                const meta = GOLD_MAINLINE_META[row.id];
                return (
                  <div key={row.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">{meta.label}</div>
                      <FAStatusPill tone="dim" dot={false}>{formatGoldPricingLayerLabel(meta.pricingLayer)}</FAStatusPill>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {meta.evidenceTargets.slice(0, 4).map((target) => (
                        <FAStatusPill key={target} tone="neutral" dot={false}>{target}</FAStatusPill>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="mt-1.5 text-[length:var(--type-caption)] text-[var(--fg-4)]">九条主线均已有后端覆盖。</div>
          )}
        </div>
        <div>
          <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">已覆盖但待验证</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {pendingRows.map((row) => (
              <FAStatusPill key={row.id} tone="warn" dot={false}>{GOLD_MAINLINE_META[row.id].shortLabel}</FAStatusPill>
            ))}
            {!pendingRows.length ? <span className="text-[length:var(--type-caption)] text-[var(--fg-4)]">暂无单源待验证主线。</span> : null}
          </div>
        </div>
      </div>
    </FACard>
  );
}

function VerificationPanel({ overview }: { overview: GoldMacroOverview }) {
  const verification = overview.verification_matrix.slice(0, 8);
  const conflictChecks = overview.driver_conflict?.verification_needed ?? [];

  return (
    <FACard title="待验证矩阵" eyebrow="Verification" accent="info" className="shrink-0">
      {verification.length || conflictChecks.length ? (
        <div className="grid gap-2">
          {conflictChecks.map((item) => (
            <div key={`conflict-${item}`} className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <ShieldAlert size={12} className="mt-0.5 shrink-0 text-[var(--warn)]" />
              <div className="min-w-0 flex-1 text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">{formatGoldDriverLabel(item)}</div>
            </div>
          ))}
          {verification.map((item) => (
            <div key={item.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">{verificationLabel(item)}</div>
                <FAStatusPill tone={statusTone(item.status)} dot={false}>{formatGoldVerificationStatusLabel(item.status)}</FAStatusPill>
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5 text-[length:var(--type-caption)] text-[var(--fg-5)]">
                {item.mainline_id ? <span>{formatGoldMainlineLabel(item.mainline_id)}</span> : null}
                {item.required_source ? <span>{formatGoldVerificationReasonLabel(item.required_source)}</span> : null}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[length:var(--type-caption)] text-[var(--fg-4)]">当前主线总览未返回待验证项。</div>
      )}
    </FACard>
  );
}

function ConflictPanel({ overview }: { overview: GoldMacroOverview }) {
  const conflict = overview.driver_conflict;
  if (!conflict) return null;

  return (
    <FACard
      title="多空冲突"
      eyebrow="Driver Conflict"
      accent={conflict.status === "aligned" ? "up" : "warn"}
      className="shrink-0"
      action={<FAStatusPill tone={goldConflictTone(conflict.status)} dot={false}>{formatGoldConflictStatusLabel(conflict.status)}</FAStatusPill>}
    >
      <div className="grid gap-3">
        <div>
          <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">利多驱动</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(conflict.bullish_drivers.length ? conflict.bullish_drivers : ["暂无"]).map((item) => (
              <FAStatusPill key={item} tone="up" dot={false}>{formatGoldDriverLabel(item)}</FAStatusPill>
            ))}
          </div>
        </div>
        <div>
          <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">利空驱动</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(conflict.bearish_drivers.length ? conflict.bearish_drivers : ["暂无"]).map((item) => (
              <FAStatusPill key={item} tone="down" dot={false}>{formatGoldDriverLabel(item)}</FAStatusPill>
            ))}
          </div>
        </div>
      </div>
    </FACard>
  );
}

function ChainPanel({ overview }: { overview: GoldMacroOverview }) {
  const chain = overview.war_oil_rate_chain;
  if (!chain) return null;

  return (
    <FACard
      title={formatTransmissionPathLabel(chain.path_id)}
      eyebrow="Transmission Chain"
      accent="warn"
      className="shrink-0"
      action={<FAStatusPill tone={goldNetBiasTone(chain.net_effect)} dot={false}>{formatGoldNetBiasLabel(chain.net_effect)}</FAStatusPill>}
    >
      <p className="text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">{formatGoldNarrativeText(chain.summary)}</p>
      {chain.steps.length ? (
        <div className="mt-3 grid gap-1.5">
          {chain.steps.map((step) => (
            <div key={step.id} className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[length:var(--type-caption)]">
              <GitBranch size={11} className="text-[var(--warn)]" />
              <span className="min-w-0 flex-1 truncate text-[var(--fg-2)]">{step.label}</span>
              <FAStatusPill tone={statusTone(step.status ?? "partial")} dot={false}>{step.status ?? "partial"}</FAStatusPill>
            </div>
          ))}
        </div>
      ) : null}
    </FACard>
  );
}

export function MainlineDetailDrawer({ overview, rows }: MainlineDetailDrawerProps) {
  return (
    <div className="grid content-start gap-3">
      <MissingCoveragePanel rows={rows} />
      <VerificationPanel overview={overview} />
      <ConflictPanel overview={overview} />
      <ChainPanel overview={overview} />
    </div>
  );
}
