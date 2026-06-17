import { Activity, Crosshair, Landmark, Orbit, Radar, Shield } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { CMEOptionsResponse } from "@/types/cme-options";
import { formatNumber, toneStyle, topWall } from "./cmeOptionsFormat";

interface CMEOptionsKpiStripProps {
  snapshot: CMEOptionsResponse;
  wallScores: CMEOptionsResponse["wall_scores"];
}

interface KpiItem {
  label: string;
  value: string;
  delta: string;
  tone: string;
  icon: LucideIcon;
}

function StatCard({ item }: { item: KpiItem }) {
  const tone = toneStyle(item.tone);
  const Icon = item.icon;

  return (
    <div
      style={{
        background: "var(--bg-card)",
        border: `1px solid ${tone.border}`,
        borderRadius: "var(--radius-lg)",
        padding: "8px 10px",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `linear-gradient(180deg, ${tone.bg}, transparent 60%)`,
          pointerEvents: "none",
        }}
      />
      <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 8 }}>
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: "50%",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            border: `1px solid ${tone.border}`,
            background: "rgba(8,13,26,0.35)",
            color: tone.text,
            flexShrink: 0,
          }}
        >
          <Icon size={11} color={tone.text} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ font: "500 9px/1 Inter", color: tone.text, marginBottom: 3 }}>{item.label}</div>
          <div className="fa-num" style={{ fontSize: 14, fontWeight: 700, color: "var(--fg-1)", fontFamily: "var(--font-mono)" }}>
            {item.value}
          </div>
          <div style={{ marginTop: 2, fontSize: 9, color: "#7f90bd" }}>{item.delta}</div>
        </div>
      </div>
    </div>
  );
}

export function CMEOptionsKpiStrip({ snapshot, wallScores }: CMEOptionsKpiStripProps) {
  const gex = snapshot.gex?.netgex_aggregate;
  const gammaZero = gex?.gamma_zero?.price;
  const netGex = gex?.net_gex;
  const direction = gex?.net_gex_direction ?? "neutral";
  const callWall = topWall(wallScores, "CALL");
  const putWall = topWall(wallScores, "PUT");

  const kpis: KpiItem[] = [
    { label: "结构状态", value: direction === "negative" ? "I1 防守" : direction === "positive" ? "I2 修复" : "中性", delta: direction === "negative" ? "偏 I1 防守" : "观察中", tone: "info", icon: Shield },
    { label: "Net GEX", value: formatNumber(netGex), delta: `方向 ${direction}`, tone: direction === "negative" ? "down" : "up", icon: Activity },
    { label: "Gamma Zero", value: formatNumber(gammaZero, 1), delta: "关键翻转价位", tone: "violet", icon: Orbit },
    { label: "当前 F", value: formatNumber(gammaZero, 1), delta: "现价参照", tone: "info", icon: Crosshair },
    { label: "主战区", value: `${formatNumber(putWall?.strike)}–${formatNumber(callWall?.strike)}`, delta: "关键波动区间", tone: "warn", icon: Radar },
    { label: "主墙位", value: `${formatNumber(putWall?.strike)}P / ${formatNumber(callWall?.strike)}C`, delta: "最强 GEX 墙位", tone: "warn", icon: Landmark },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(6,minmax(0,1fr))", gap: 8 }}>
      {kpis.map((item) => <StatCard key={item.label} item={item} />)}
    </div>
  );
}
