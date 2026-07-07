import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  GOLD_MAINLINE_META,
  formatGoldMainlineLabel,
  formatGoldNetBiasLabel,
  formatGoldPricingLayerLabel,
  formatGoldVerificationStatusLabel,
  goldNetBiasTone,
  goldVerificationStatusTone,
} from "@/components/shared/goldMainlineFormat";
import {
  coverageStatusLabel,
  coverageStatusTone,
  scoreFormulaLabel,
  scoreLabel,
  type MainlineCoverageRow,
} from "./goldMainlineCoverage";

interface MainlineRankingTableProps {
  rows: MainlineCoverageRow[];
}

export function MainlineRankingTable({ rows }: MainlineRankingTableProps) {
  return (
    <FACard title="九主线覆盖矩阵" eyebrow="Theme Coverage" accent="brand" bodyClassName="!p-0" className="shrink-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[940px] table-fixed text-left text-[length:var(--type-caption)]">
          <colgroup>
            <col className="w-[58px]" />
            <col className="w-[178px]" />
            <col className="w-[92px]" />
            <col className="w-[82px]" />
            <col className="w-[74px]" />
            <col className="w-[66px]" />
            <col className="w-[104px]" />
            <col className="w-[86px]" />
            <col />
          </colgroup>
          <thead className="border-b border-[var(--border-faint)] bg-[var(--bg-card-inner)] text-[var(--fg-5)]">
            <tr>
              <th className="px-3 py-2 font-semibold">Rank</th>
              <th className="px-3 py-2 font-semibold">主线</th>
              <th className="px-3 py-2 font-semibold">定价层</th>
              <th className="px-3 py-2 font-semibold">覆盖</th>
              <th className="px-3 py-2 font-semibold">方向</th>
              <th className="px-3 py-2 font-semibold">评分</th>
              <th className="px-3 py-2 font-semibold">验证</th>
              <th className="px-3 py-2 font-semibold">证据</th>
              <th className="px-3 py-2 font-semibold">摘要</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const meta = GOLD_MAINLINE_META[row.id];
              const item = row.ranking;
              const verificationStatus = item?.verification_status ?? (row.status === "missing" ? "unverified" : "pending");
              return (
                <tr key={row.id} className="border-b border-[var(--border-faint)] last:border-0">
                  <td className="px-3 py-2 fa-num font-semibold text-[var(--fg-2)]">{item ? `#${item.rank}` : "--"}</td>
                  <td className="px-3 py-2">
                    <div className="font-semibold text-[var(--fg-2)]">{item?.label || meta.label || formatGoldMainlineLabel(row.id)}</div>
                    <div className="mt-0.5 line-clamp-1 text-[length:var(--type-caption)] text-[var(--fg-5)]">{meta.headline}</div>
                  </td>
                  <td className="px-3 py-2 text-[var(--fg-3)]">{formatGoldPricingLayerLabel(item?.pricing_layer ?? meta.pricingLayer)}</td>
                  <td className="px-3 py-2">
                    <FAStatusPill tone={coverageStatusTone(row.status)} dot={false}>{coverageStatusLabel(row.status)}</FAStatusPill>
                  </td>
                  <td className="px-3 py-2">
                    <FAStatusPill tone={goldNetBiasTone(item?.direction ?? "unknown")} dot={false}>{formatGoldNetBiasLabel(item?.direction ?? "unknown")}</FAStatusPill>
                  </td>
                  <td className="px-3 py-2">
                    <div className="fa-num font-semibold text-[var(--fg-2)]">{scoreLabel(item?.theme_score ?? item?.score)}</div>
                    <div className="mt-0.5 text-[length:var(--type-caption)] text-[var(--fg-5)]">D/I/C/F {scoreFormulaLabel(item)}</div>
                  </td>
                  <td className="px-3 py-2">
                    <FAStatusPill tone={goldVerificationStatusTone(verificationStatus)} dot={false}>{formatGoldVerificationStatusLabel(verificationStatus)}</FAStatusPill>
                  </td>
                  <td className="px-3 py-2">
                    <div className="fa-num text-[var(--fg-2)]">{row.eventIds.length}E / {row.sourceCount}S</div>
                  </td>
                  <td className="min-w-0 px-3 py-2 text-[var(--fg-3)]">
                    <div className="line-clamp-2 max-w-full break-words leading-5">
                      {item?.summary || `待接入：${meta.evidenceTargets.slice(0, 3).join(" / ")}`}
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
