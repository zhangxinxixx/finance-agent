import { AlertTriangle, Layers, Target } from "lucide-react";

interface ResonanceItem {
  px: string;
  macro: string;
  options: string;
  verdict: string;
  kind: "support" | "pivot" | "resist" | "risk";
  core: boolean;
}

export function DashboardCompositeSummaryBlock({
  compositeSummary,
  confidencePct,
}: {
  compositeSummary: string;
  confidencePct: number | null;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 12,
        padding: "10px 12px",
        background: "var(--bg-card-inner)",
        border: "1px solid var(--border)",
        borderRadius: 3,
      }}
    >
      <Target size={13} color="var(--brand-hover)" style={{ flexShrink: 0, marginTop: 2 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            font: "600 9px/1 Inter",
            color: "var(--fg-5)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            marginBottom: 4,
          }}
        >
          综合结论
        </div>
        <div style={{ fontSize: 13, color: "var(--fg-2)", lineHeight: 1.6 }}>{compositeSummary}</div>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
          paddingLeft: 12,
          borderLeft: "1px solid var(--border)",
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 8, color: "var(--fg-5)", letterSpacing: "0.08em", textTransform: "uppercase" }}>确信度</span>
        <span className="fa-num" style={{ font: "700 22px/1 JetBrains Mono", color: "#f59e0b" }}>
          {confidencePct ?? "—"}
        </span>
        <span style={{ fontSize: 9, color: "var(--fg-5)" }}>/ 100</span>
      </div>
    </div>
  );
}

export function DashboardCompositeResonanceTable({ items }: { items: ResonanceItem[] }) {
  if (!items.length) {
    return null;
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <Layers size={12} color="var(--brand-hover)" />
        <span style={{ font: "600 12px/1 Inter", color: "var(--fg-2)" }}>关键位速览</span>
        <span style={{ fontSize: 10, color: "var(--fg-5)" }}>基于当前期权结构与综合结论</span>
      </div>
      <div style={{ background: "var(--bg-card-inner)", border: "1px solid var(--border)", borderRadius: 3, overflow: "hidden" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "112px 1.1fr 1.3fr 1fr",
            padding: "7px 12px",
            background: "var(--bg-panel)",
            borderBottom: "1px solid var(--border)",
            font: "600 9px/1 Inter",
            color: "var(--fg-5)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          <span>价位</span>
          <span>宏观含义</span>
          <span>期权含义</span>
          <span>综合判断</span>
        </div>
        {items.map((r, i) => {
          const pxColor = r.kind === "support" ? "var(--up)" : r.kind === "resist" ? "var(--down)" : r.kind === "risk" ? "var(--warn)" : "var(--brand-hover)";
          return (
            <div
              key={`${r.kind}-${r.px}-${i}`}
              style={{
                display: "grid",
                gridTemplateColumns: "112px 1.1fr 1.3fr 1fr",
                padding: "8px 12px",
                borderBottom: i === items.length - 1 ? 0 : "1px solid var(--border)",
                alignItems: "center",
                fontSize: 11,
                lineHeight: 1.5,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ width: 3, height: 14, background: pxColor, borderRadius: 1 }} />
                <span className="fa-num" style={{ color: pxColor, fontWeight: 700, fontSize: 12 }}>
                  {r.px}
                </span>
              </div>
              <span style={{ color: "var(--fg-3)" }}>{r.macro}</span>
              <span style={{ color: "var(--fg-3)" }}>{r.options}</span>
              <span style={{ color: r.core ? "var(--fg-2)" : "var(--fg-3)", fontWeight: r.core ? 600 : 400 }}>{r.verdict}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function DashboardCompositeRevisionBlock({ revision }: { revision: string }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "8px 10px", background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.18)", borderRadius: 3 }}>
      <AlertTriangle size={12} color="#f59e0b" style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ flex: 1 }}>
        <span style={{ font: "600 9px/1 Inter", color: "#f59e0b", letterSpacing: "0.08em", textTransform: "uppercase", marginRight: 8 }}>改判条件</span>
        <span style={{ fontSize: 11, color: "var(--fg-3)", lineHeight: 1.6 }}>{revision}</span>
      </div>
    </div>
  );
}
