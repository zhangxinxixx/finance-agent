import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldDriverLabel,
  goldConflictTone,
} from "@/components/shared/goldMainlineFormat";
import type { DriverConflict } from "@/types/gold-mainlines";

interface SafeHavenVsInflationSplitProps {
  conflict: DriverConflict | null;
}

export function SafeHavenVsInflationSplit({ conflict }: SafeHavenVsInflationSplitProps) {
  return (
    <FACard
      title="多空冲突拆解"
      eyebrow="Conflict Split"
      accent={conflict?.status === "aligned" ? "up" : "warn"}
      className="shrink-0"
      action={<FAStatusPill tone={goldConflictTone(conflict?.status)} dot={false}>{conflict?.status ?? "unknown"}</FAStatusPill>}
    >
      {conflict ? (
        <div className="grid gap-3">
          {conflict.explanation ? <p className="text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">{conflict.explanation}</p> : null}
          <div className="grid gap-2 md:grid-cols-2">
            <div>
              <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">避险利多</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {(conflict.bullish_drivers.length ? conflict.bullish_drivers : ["暂无"]).map((driver) => (
                  <FAStatusPill key={driver} tone="up" dot={false}>{formatGoldDriverLabel(driver)}</FAStatusPill>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">通胀/利率利空</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {(conflict.bearish_drivers.length ? conflict.bearish_drivers : ["暂无"]).map((driver) => (
                  <FAStatusPill key={driver} tone="down" dot={false}>{formatGoldDriverLabel(driver)}</FAStatusPill>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-[length:var(--type-caption)] text-[var(--fg-4)]">当前主线总览未返回多空冲突拆解。</div>
      )}
    </FACard>
  );
}
