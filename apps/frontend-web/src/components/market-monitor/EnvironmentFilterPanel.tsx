import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { MarketEnvironmentFilterKey, MarketMonitorMockFile } from "@/types/market-monitor";
import { textOrDash } from "./format";

interface EnvironmentFilterPanelProps {
  environmentFilters: MarketMonitorMockFile["environment_filters"];
}

const FILTER_ORDER: MarketEnvironmentFilterKey[] = ["us10y", "dxy", "us02y", "xauusd_price_reaction"];
const FILTER_META: Record<MarketEnvironmentFilterKey, { zh: string; zhHint: string }> = {
  us10y: { zh: "10Y 美债收益", zhHint: "名义利率锚" },
  dxy: { zh: "美元指数", zhHint: "汇率通道" },
  us02y: { zh: "2Y 美债收益", zhHint: "短端利率" },
  xauusd_price_reaction: { zh: "黄金价格反应", zhHint: "联动方向" },
};
const STAT_BOX_CLASS_NAME = "rounded-md border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2";

export function EnvironmentFilterPanel({ environmentFilters }: EnvironmentFilterPanelProps) {
  return (
    <FACard title="环境过滤器" eyebrow="做单条件滤网" accent="info">
      <div className="space-y-2">
        {FILTER_ORDER.map((key) => {
          const item = environmentFilters?.[key];
          const meta = FILTER_META[key];

          return (
            <div
              key={key}
              className="rounded-lg border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[11px] font-semibold text-[var(--fg-2)]">{meta.zh}</div>
                  <div className="mt-0.5 text-[9px] text-[var(--fg-5)]">{meta.zhHint}</div>
                </div>
                <FAStatusPill
                  tone={
                    item?.status === "ok"
                      ? "up"
                      : item?.status === "warn"
                        ? "warn"
                        : item?.status === "error"
                          ? "down"
                          : "neutral"
                  }
                >
                  {item?.status ?? "—"}
                </FAStatusPill>
              </div>

              <div className="mt-3 grid grid-cols-3 gap-2">
                <div className={STAT_BOX_CLASS_NAME}>
                  <div className="text-[8px] font-semibold text-[var(--fg-5)]">最新值</div>
                  <div className="mt-1 font-mono text-[12px] text-[var(--fg-2)]">
                    {textOrDash(item?.latest_value)}
                    {item?.unit ? <span className="ml-1 text-[9px] text-[var(--fg-5)]">{item.unit}</span> : null}
                  </div>
                </div>
                <div className={STAT_BOX_CLASS_NAME}>
                  <div className="text-[8px] font-semibold text-[var(--fg-5)]">1 周变动</div>
                  <div className="mt-1 font-mono text-[12px] text-[var(--fg-2)]">{textOrDash(item?.one_week_change)}</div>
                </div>
                <div className={STAT_BOX_CLASS_NAME}>
                  <div className="text-[8px] font-semibold text-[var(--fg-5)]">1 月变动</div>
                  <div className="mt-1 font-mono text-[12px] text-[var(--fg-2)]">{textOrDash(item?.one_month_change)}</div>
                </div>
              </div>

              <p className="mt-2 text-[10px] leading-5 text-[var(--fg-4)]">
                {textOrDash(item?.interpretation, "暂无过滤条件解读。")}
              </p>
            </div>
          );
        })}
      </div>
    </FACard>
  );
}
