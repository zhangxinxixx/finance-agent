interface FactorItem {
  type: string;
  name: string;
  color: string;
  description: string;
  icon: string;
}

const FACTOR_PANEL_ITEMS: FactorItem[] = [
  {
    type: "DRIVER",
    name: "美元走弱",
    color: "#60a5fa",
    description: "DXY 跌破 104 关键支撑，美元指数连续三周下行，推动黄金估值重估。",
    icon: "D",
  },
  {
    type: "TAILWIND",
    name: "实际利率下行",
    color: "#34d399",
    description: "10Y TIPS 实际利率回落至 2.0% 以下，降低持有黄金的机会成本。",
    icon: "R",
  },
  {
    type: "HEADWIND",
    name: "通胀预期分化",
    color: "#f59e0b",
    description: "T10YIE 与核心 PCE 出现背离，市场对降息路径定价存在分歧。",
    icon: "I",
  },
];

export function FactorPanel() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        background: "var(--bg-panel)",
        border: "1px solid var(--border-faint)",
        borderRadius: "var(--radius-lg)",
        height: "100%",
      }}
    >
      {FACTOR_PANEL_ITEMS.map((item, index) => (
        <div
          key={item.type}
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            padding: "9px 10px",
            borderLeft: `2px solid ${item.color}`,
            borderBottom: index < FACTOR_PANEL_ITEMS.length - 1 ? "1px solid var(--border-faint)" : undefined,
          }}
        >
          <FactorPanelBlock
            type={item.type}
            color={item.color}
            icon={item.icon}
            name={item.name}
            description={item.description}
          />
        </div>
      ))}

      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "9px 10px",
          borderLeft: "2px solid #f59e0b",
          borderTop: "1px solid var(--border-faint)",
        }}
      >
        <FactorPanelBlock
          type="ALERT"
          color="#f59e0b"
          icon="!"
          name="背离预警"
          description="T10YIE 与 DXY 走势背离扩大，关注后续收敛信号。"
        />
      </div>
    </div>
  );
}

function FactorPanelBlock({
  type,
  color,
  icon,
  name,
  description,
}: {
  type: string;
  color: string;
  icon: string;
  name: string;
  description: string;
}) {
  return (
    <>
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontWeight: 500,
          fontSize: 8,
          lineHeight: 1,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--fg-5)",
          marginBottom: 6,
        }}
      >
        {type}
      </div>
      <div className="flex items-start gap-2">
        <div
          style={{
            width: 18,
            height: 18,
            borderRadius: 3,
            background: `${color}1a`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            fontFamily: "var(--font-sans)",
            fontWeight: 700,
            fontSize: 9,
            color,
          }}
        >
          {icon}
        </div>
        <div className="min-w-0">
          <div
            style={{
              fontFamily: "var(--font-sans)",
              fontWeight: 700,
              fontSize: 11,
              lineHeight: 1,
              color,
            }}
          >
            {name}
          </div>
          <div
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 9.5,
              lineHeight: 1.5,
              color: "var(--fg-4)",
              marginTop: 4,
            }}
          >
            {description}
          </div>
        </div>
      </div>
    </>
  );
}

export default FactorPanel;
