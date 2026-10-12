import type { ResearchIdentity as Identity } from "@/types/research-identity";
import { ResearchDetails } from "./ResearchDetails";
import { beijingTime } from "@/components/dashboard/DashboardResearchBriefModel";

export function ResearchIdentity({ identity }: { identity?: Identity | null }) {
  const validity = identity?.key_level_validity;
  const time = (value?: string | null) => value ? beijingTime(value) : "未知";
  const status = { active: "有效", expired: "已失效", unavailable: "不可用", historical: "历史参考" };
  return <section aria-label="研究时点与点位有效性" className="fa-muted-text">
    <p>研究版本：{identity?.research_version ?? "未知"} · 交易日：{identity?.trade_date ?? "未知"}</p>
    <p>研究数据时点：{time(identity?.data_as_of)} · 点位状态：{validity ? status[validity.status] : "未知"}</p>
    <p>点位数据时点：{time(validity?.data_as_of)} · 有效截止：{time(validity?.valid_until)}</p>
    <ResearchDetails label="查看研究身份与状态依据">
      <p>report_id：{identity?.report_id ?? "未知"} · run_id：{identity?.run_id ?? "未知"}</p>
      <p>snapshot_id：{identity?.snapshot_id ?? "未知"} · 生成时间：{time(identity?.generated_at)}</p>
      <p>后端原因码：{validity?.reason_codes.length ? validity.reason_codes.join("、") : "未提供"}</p>
    </ResearchDetails>
  </section>;
}
