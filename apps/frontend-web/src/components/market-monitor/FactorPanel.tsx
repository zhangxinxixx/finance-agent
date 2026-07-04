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
    <div className="market-monitor-factor-panel">
      {FACTOR_PANEL_ITEMS.map((item, index) => (
        <div
          key={item.type}
          className="market-monitor-factor-panel-row"
          style={{
            borderLeftColor: item.color,
            borderBottomColor: index < FACTOR_PANEL_ITEMS.length - 1 ? "var(--border-faint)" : "transparent",
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

      <div className="market-monitor-factor-panel-row market-monitor-factor-panel-row--alert">
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
      <div className="market-monitor-factor-panel-type">
        {type}
      </div>
      <div className="market-monitor-factor-panel-body">
        <div className="market-monitor-factor-panel-icon" style={{ backgroundColor: `${color}1a`, color }}>
          {icon}
        </div>
        <div className="min-w-0">
          <div className="market-monitor-factor-panel-name" style={{ color }}>
            {name}
          </div>
          <div className="market-monitor-factor-panel-description">
            {description}
          </div>
        </div>
      </div>
    </>
  );
}

export default FactorPanel;
