import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { useFedWatch } from "@/hooks/useFedWatch";

function number(value: number | null | undefined, digits = 2) {
  return value == null ? "—" : value.toFixed(digits);
}
function probability(value: number | null | undefined) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function FedWatchPanel() {
  const { data, loading, error } = useFedWatch();
  const status = data?.source_health.status ?? "missing";
  const fresh = !error && status === "fresh";
  const labels: Record<string, string> = { fresh: "有效", stale: "过期 · 仅供历史参考", missing: "暂无概率快照", parse_failed: "数据解析失败" };
  const directions: Record<string, string> = { hawkish: "偏鹰", dovish: "偏鸽", neutral: "中性" };
  const strengths: Record<string, string> = { weak: "弱", medium: "中", strong: "强" };
  const meetings = data?.factor.market_implied_path.meetings ?? [];
  return <FACard title="美联储市场隐含路径（FedWatch）" eyebrow="CME · 市场隐含预期" className="shrink-0">
    <div className="space-y-3 fa-body-text" data-testid="fedwatch-panel">
      <FAStatusPill tone={fresh ? "up" : "warn"}>
        {loading ? "正在读取" : error ? "FedWatch 服务暂不可用" : labels[status] ?? "数据不可用"}
      </FAStatusPill>
      <p className="fa-muted-text">下一次美联储议息会议（FOMC）：{data?.next_meeting?.meeting_date ?? "—"} · 年底会议：{data?.year_end?.meeting_date ?? "—"}</p>
      <p>政策路径重定价：{fresh ? directions[data?.repricing.direction ?? ""] ?? "证据不足" : "不可用"}
        {fresh && data?.repricing.strength ? ` · 强度 ${strengths[data.repricing.strength] ?? "—"}` : ""}</p>
      {meetings.length > 0 ? <div className="overflow-x-auto">
        <table className="w-full text-left fa-body-text tabular-nums">
          <thead className="fa-label"><tr>{["会议", "低于 / 等于 / 高于当前区间", "中点期望 %", "变化（bp）", "日变化（bp）", "周变化（bp）", "月变化（bp）"].map(x => <th className="p-2" key={x}>{x}</th>)}</tr></thead>
          <tbody>{meetings.map(m => <tr key={m.meeting_date} className="border-t border-[var(--border)]">
            <td className="p-2">{m.meeting_date}</td>
            <td className="p-2">{probability(m.prob_below_current_target === undefined ? m.cut_probability : m.prob_below_current_target)} / {probability(m.prob_at_current_target === undefined ? m.hold_probability : m.prob_at_current_target)} / {probability(m.prob_above_current_target === undefined ? m.hike_probability : m.prob_above_current_target)}</td>
            <td className="p-2">{number(m.expected_rate_pct, 3)}</td><td className="p-2">{number(m.expected_change_bp)}</td>
            {["1d", "1w", "1m"].map(w => <td className="p-2" key={w}>{fresh ? number(m.comparisons[w]?.expected_rate_delta_bp) : "—"}</td>)}
          </tr>)}</tbody>
        </table>
        <details className="mt-3"><summary>各会议目标区间概率</summary>
          {meetings.map(m => <p className="mt-2" key={m.meeting_date}>{m.meeting_date}：{m.bins.map(b => `${number(b.target_low)}–${number(b.target_high)}%：${probability(b.probability)}`).join("；")}</p>)}
        </details>
      </div> : <p className="fa-muted-text">尚无可核验的未来会议概率；政策路径分析降级，其他宏观模块继续可用。</p>}
      <p className="fa-muted-text">数据时点：{data?.as_of ?? "—"}。Δ 单位为 bp；缺失不是零。FedWatch 是市场预期，不是美联储承诺。</p>
      <p className="fa-muted-text">概率表示会议后的目标区间相对当前区间的位置，不是该次会议单独加降息的概率；中点期望不等于实际有效联邦基金利率。</p>
      <a className="text-[var(--brand)]" href="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html" target="_blank" rel="noreferrer">CME 官方来源</a>
      {data?.snapshot_id && <ResearchDetails label="查看数据记录"><p className="fa-faint-text break-all">snapshot_id：{data.snapshot_id}</p></ResearchDetails>}
    </div>
  </FACard>;
}
