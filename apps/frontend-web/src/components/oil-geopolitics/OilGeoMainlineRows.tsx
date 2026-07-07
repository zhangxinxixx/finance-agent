import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  GOLD_MAINLINE_META,
  formatGoldNetBiasLabel,
  formatGoldPricingLayerLabel,
  formatGoldVerificationStatusLabel,
  goldNetBiasTone,
  goldVerificationStatusTone,
} from "@/components/shared/goldMainlineFormat";
import {
  coverageStatusLabel,
  coverageStatusTone,
  scoreLabel,
  type TopicMainlineRow,
} from "@/components/oil-geopolitics/oilGeopoliticsModel";

export function OilGeoMainlineRows({ rows }: { rows: TopicMainlineRow[] }) {
  return (
    <FACard title="地缘 / 石油主线" eyebrow="Theme Rows" accent="brand" bodyClassName="!p-0" className="shrink-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[780px] table-fixed text-left text-[length:var(--type-caption)]">
          <colgroup>
            <col className="w-[62px]" />
            <col className="w-[150px]" />
            <col className="w-[92px]" />
            <col className="w-[82px]" />
            <col className="w-[76px]" />
            <col className="w-[110px]" />
            <col />
          </colgroup>
          <thead className="border-b border-[var(--border-faint)] bg-[var(--bg-card-inner)] text-[var(--fg-5)]">
            <tr>
              <th className="px-3 py-2 font-semibold">Rank</th>
              <th className="px-3 py-2 font-semibold">主线</th>
              <th className="px-3 py-2 font-semibold">覆盖</th>
              <th className="px-3 py-2 font-semibold">方向</th>
              <th className="px-3 py-2 font-semibold">Score</th>
              <th className="px-3 py-2 font-semibold">验证</th>
              <th className="px-3 py-2 font-semibold">摘要 / 证据</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const item = row.ranking;
              const meta = GOLD_MAINLINE_META[row.id];
              const verificationStatus = item?.verification_status ?? (row.status === "missing" ? "unverified" : "pending");

              return (
                <tr key={row.id} className="border-b border-[var(--border-faint)] last:border-0">
                  <td className="fa-num px-3 py-2 font-semibold text-[var(--fg-2)]">{item ? `#${item.rank}` : "-"}</td>
                  <td className="px-3 py-2">
                    <div className="font-semibold text-[var(--fg-2)]">{item?.label || meta.label}</div>
                    <div className="mt-0.5 text-[length:var(--type-caption)] text-[var(--fg-5)]">{formatGoldPricingLayerLabel(meta.pricingLayer)}</div>
                  </td>
                  <td className="px-3 py-2">
                    <FAStatusPill tone={coverageStatusTone(row.status)} dot={false}>{coverageStatusLabel(row.status)}</FAStatusPill>
                  </td>
                  <td className="px-3 py-2">
                    <FAStatusPill tone={goldNetBiasTone(item?.direction ?? "unknown")} dot={false}>{formatGoldNetBiasLabel(item?.direction ?? "unknown")}</FAStatusPill>
                  </td>
                  <td className="fa-num px-3 py-2 font-semibold text-[var(--fg-2)]">{scoreLabel(item?.score)}</td>
                  <td className="px-3 py-2">
                    <FAStatusPill tone={goldVerificationStatusTone(verificationStatus)} dot={false}>{formatGoldVerificationStatusLabel(verificationStatus)}</FAStatusPill>
                  </td>
                  <td className="px-3 py-2 text-[var(--fg-3)]">
                    <div className="line-clamp-2 leading-5">{item?.summary || meta.description}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {meta.evidenceTargets.slice(0, 4).map((target) => (
                        <span key={target} className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-1.5 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-5)]">{target}</span>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </FACard>
  );
}
