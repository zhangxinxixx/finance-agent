# Market Monitor Page Spec

## 页面目标
展示 XAUUSD / DXY 实时行情、关键宏观指标快照、市场概率数据。不做实时交易信号，仅做只读监控。

## 路由
`/market-monitor`

## 页面模块

```
MarketMonitorPage
├── DateSelector              # 日期选择器
├── TickerTape                # 实时行情条
│   ├── TickerItem (XAUUSD)
│   ├── TickerItem (XAGUSD)
│   ├── TickerItem (DXY)
│   └── TickerItem (可选)
├── MacroIndicatorPanel       # 宏观指标面板
│   ├── IndicatorRow           # 指标行 (6 指标)
│   ├── MacroPhaseBadge        # 宏观三态标签
│   └── 7-driver evaluation 表
├── MarketOddsPanel           # 市场概率面板 (P4-09)
│   ├── EventCards             # 事件概率卡片
│   └── SourceStatus           # 各源状态
└── SourceTrace               # 页面级溯源
```

## 组件树

```
AppShell
└── MarketMonitorPage
    ├── DateSelector (shared)
    ├── TickerTape
    │   └── TickerItem × 4
    │       └── StatusBadge (shared)
    ├── MacroIndicatorPanel
    │   ├── MetricCardRow (shared)
    │   │   └── MetricCard × 6 (shared)
    │   └── MacroPhaseBadge (shared)
    ├── MarketOddsPanel
    │   └── EventCard × N
    └── SourceTrace (shared)
```

## 输入数据

| 数据 | API Endpoint | 类型 |
|------|-------------|------|
| 市场指标 | `GET /api/market/tickers` | `MarketTickers` |
| 宏观数据 | `GET /api/macro/latest` | `MacroLatest` |
| 宏观报告 | `GET /api/macro/report?date=X` | `MacroReport` |
| 市场概率 | `GET /api/market-odds/report?date=X` | `MarketOddsReport` |
| 日期列表 | `GET /api/reports/dates` | `UnifiedDatesResponse` |

## Mock 数据文件

`src/mocks/market-monitor.json`：

```json
{
  "tickers": {
    "xauusd": { "price": 3265.40, "change_pct": 0.82, "source": "jin10_mcp_realtime" },
    "xagusd": { "price": 35.82, "change_pct": 1.25, "source": "jin10_mcp_realtime" },
    "dxy": { "value": 105.82, "unit": "index", "source": "macro_latest" },
    "real_10y": { "value": 1.98, "unit": "%", "source": "macro_latest" }
  },
  "macro": {
    "as_of": "2026-05-17",
    "indicators": {
      "DXY": { "value": 105.82, "unit": "index" },
      "REAL_10Y": { "value": 1.98, "unit": "%" },
      "T10YIE": { "value": 2.31, "unit": "%" },
      "ON_RRP": { "value": 327.5, "unit": "B" },
      "TGA": { "value": 842.3, "unit": "B" },
      "IORB": { "value": 4.40, "unit": "%" }
    }
  },
  "odds": {
    "status": "available",
    "aggregate_signal": "moderately_bullish",
    "events": [
      {
        "event_id": "fomc_2026_06",
        "event_name": "FOMC June 2026",
        "status": "available",
        "final_probability": 0.72,
        "interpretation": "72% probability of hold, gold supportive"
      }
    ]
  }
}
```

## API Schema

```typescript
interface MarketTickers {
  generated_at: string;
  sources: string[];
  tickers: Record<string, TickerData | MacroTickerData>;
}

interface TickerData {
  price?: number;
  change_pct?: number | null;
  bid?: number | null;
  ask?: number | null;
  source: string;
}

interface MacroTickerData {
  value: number | string;
  unit: string;
  source: string;
}
```

## 加载状态
- TickerTape: 4 个 skeleton 条（宽 120px + pulse）
- MacroIndicatorPanel: 6 个 MetricCard skeleton
- MarketOddsPanel: 2 个 EventCard skeleton

## 空状态
- 无实时报价：显示 CME 最近结算价 + "延迟数据" badge
- 无宏观数据：显示 "暂无宏观数据" 占位 + 引导运行 premarket
- 无市场概率：显示 "概率数据 unavailable" + 原因标注

## 错误状态
- Jin10 MCP 不可用：降级到 CME snapshot + "实时数据不可用" 提示
- Macro API 不可用：显示上次缓存时间 + "数据可能过期"

## 验收标准
- [ ] 行情条正确显示 XAUUSD 价格和涨跌幅
- [ ] 涨跌颜色正确（绿涨红跌）
- [ ] 数据来源标注清晰（Jin10 / CME / FRED）
- [ ] 宏观三态判断正确显示（rate_pressure / transition_release / trend_tailwind）
- [ ] 市场概率事件卡片显示 final_probability + interpretation
- [ ] SourceTrace 显示所有数据源和 snapshot_id
- [ ] unavailable 模块显式标注
