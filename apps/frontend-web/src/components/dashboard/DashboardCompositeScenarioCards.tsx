import { BookOpen } from "lucide-react";

interface ScriptItem {
  tag: string;
  title: string;
  color: string;
  trigger: string;
  target: string;
  invalid: string;
  rr: string;
}

const scripts: ScriptItem[] = [
  {
    tag: "主方案",
    title: "区间拉锯",
    color: "#f59e0b",
    trigger: "4500 上方震荡，未有效跌破",
    target: "4575 / 4600",
    invalid: "跌破 4450",
    rr: "1:1.4",
  },
  {
    tag: "备选一",
    title: "转强突破",
    color: "#10b981",
    trigger: "有效站稳 4600 且回踩不破",
    target: "4650 / 4700",
    invalid: "跌回 4600 下方",
    rr: "1:2.2",
  },
  {
    tag: "备选二",
    title: "反转做空",
    color: "#f05252",
    trigger: "跌破 4500 且回抽失败",
    target: "4450 / 4400 / 4300",
    invalid: "重新站回 4500",
    rr: "1:2.4",
  },
];

export function DashboardCompositeScenarioCards() {
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <BookOpen size={12} color="var(--brand-hover)" />
        <span style={{ font: "600 12px/1 Inter", color: "var(--fg-2)" }}>交易剧本</span>
        <span style={{ fontSize: 10, color: "var(--fg-5)" }}>主方案 + 2 备选</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8 }}>
        {scripts.map((script) => (
          <div key={script.tag} style={{ background: "var(--bg-card-inner)", border: `1px solid ${script.color}33`, borderRadius: 3, padding: 10, position: "relative", overflow: "hidden" }}>
            <div style={{ position: "absolute", top: 0, left: 0, bottom: 0, width: 2, background: script.color }} />
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 6, paddingLeft: 6 }}>
              <span style={{ font: "600 10px/1.3 Inter", color: script.color }}>{script.tag}</span>
              <span style={{ fontSize: 9, color: "var(--fg-5)" }}>
                R:R <span className="fa-num" style={{ color: "var(--fg-3)" }}>{script.rr}</span>
              </span>
            </div>
            <div style={{ font: "600 11px/1.3 Inter", color: "var(--fg-2)", marginBottom: 8, paddingLeft: 6 }}>{script.title}</div>
            <div style={{ display: "grid", gap: 8, paddingLeft: 6 }}>
              <div style={{ display: "grid", gridTemplateColumns: "54px 1fr", gap: 8, alignItems: "start" }}>
                <div style={{ fontSize: 9, color: "var(--fg-5)" }}>触发条件</div>
                <div style={{ fontSize: 10, color: "var(--fg-3)", lineHeight: 1.5 }}>{script.trigger}</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "54px 1fr", gap: 8, alignItems: "start" }}>
                <div style={{ fontSize: 9, color: "var(--fg-5)" }}>目标位</div>
                <div style={{ fontSize: 10, color: "var(--fg-3)", lineHeight: 1.5 }}>{script.target}</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "54px 1fr", gap: 8, alignItems: "start" }}>
                <div style={{ fontSize: 9, color: "var(--fg-5)" }}>失效条件</div>
                <div style={{ fontSize: 10, color: "var(--fg-3)", lineHeight: 1.5 }}>{script.invalid}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
