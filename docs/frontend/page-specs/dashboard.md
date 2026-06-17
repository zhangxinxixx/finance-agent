# Dashboard Page Spec

## 页面目标
作为金融分析中台的首页，提供当日黄金市场的一站式总览：核心结论、关键指标、数据流水线状态、策略信号、风险预警。

## 路由
`/` 或 `/dashboard`

## 页面模块

```
DashboardPage
├── DateSelector              # 交易日期选择器 (共享组件)
├── ConclusionCard            # 今日核心结论卡
│   ├── Bias 方向标签
│   ├── 上方关键位 (Resistance)
│   ├── 下方支撑位 (Support)
│   ├── 宏观状态 (Macro Phase)
│   └── 期权结构摘要 (Options Summary)
├── MetricCardRow             # 6 指标卡片行
│   ├── XAUUSD
│   ├── DXY
│   ├── 10Y 实际利率
│   ├── T10YIE
│   ├── ON RRP
│   └── TGA
├── PipelineStepper           # 数据处理流水线
│   └── 6 步: raw → parsed → features → agent → report → knowledge
├── TwoColumnRow
│   ├── LatestReportsCard     # 最新报告列表
│   └── TaskQueueCard         # 今日任务队列
├── QuadGrid
│   ├── MacroTristateCard     # 宏观三态
│   ├── CMEWallSummaryCard    # CME 期权墙位
│   ├── PositioningIntentCard # 机构持仓意图 (P1)
│   └── RiskAlertsCard        # 风险预警
└── SourceTrace               # 页面级数据溯源
```

## 组件树

```
AppShell
└── DashboardPage
    ├── DateSelector (shared)
    ├── ConclusionCard (shared)
    │   └── StatusBadge (shared)
    ├── MetricCardRow
    │   └── MetricCard × 6 (shared)
    ├── PipelineStepper (shared)
    ├── LatestReportsCard
    │   └── MiniList (shared)
    ├── TaskQueueCard
    │   └── MiniList (shared)
    ├── MacroTristateCard
    ├── CMEWallSummaryCard
    ├── PositioningIntentCard
    ├── RiskAlertsCard
    │   └── RiskPanel (shared)
    └── SourceTrace (shared)
```

## 输入数据

| 数据 | API Endpoint | 类型 |
|------|-------------|------|
| 日期列表 | `GET /api/reports/dates` | `UnifiedDatesResponse` |
| 综合结论 | `GET /api/dashboard/summary` | `DashboardSummary` |
| 综合报告 | `GET /api/final-report?date=X&run_id=Y` | `FinalReport` |
| 策略卡片 | `GET /api/strategy-card?date=X&run_id=Y` | `StrategyCard` |
| 宏观数据 | `GET /api/macro/latest` | `MacroLatest` |
| CME 期权 | `GET /api/options/snapshot?date=X` | `OptionsSnapshot` |
| 报告索引 | `GET /api/reports/index` | `ReportsIndex` |
| 最近任务 | `GET /dashboard/system-status` | `SystemStatus` |
| 市场指标 | `GET /api/market/tickers` | `MarketTickers` |

## Mock 数据文件

`src/mocks/dashboard.json`：

```json
{
  "dates": [
    {
      "trade_date": "2026-05-17",
      "modules": ["macro", "options", "final_report", "strategy_card", "market_odds"],
      "latest_run_id": "550e8400-e29b-41d4-a716-446655440000",
      "has_final_report": true,
      "has_strategy_card": true
    }
  ],
  "summary": {
    "options": {
      "trade_date": "2026-05-17",
      "product": "GC",
      "expiries": ["2026-06", "2026-08", "2026-10"],
      "intent": "neutral-bullish",
      "intent_score": 0.62,
      "gamma_zero": 3225.5,
      "walls": {
        "resistance": [{"strike": 3300, "score": 0.87, "distance_pct": 1.02}],
        "support": [{"strike": 3180, "score": 0.91, "distance_pct": -2.65}]
      }
    },
    "macro": {
      "indicators": {
        "DXY": {"value": 106.02, "unit": "index"},
        "T10YIE": {"value": 2.35, "unit": "%"},
        "REAL_10Y": {"value": 2.08, "unit": "%"}
      }
    },
    "pipeline": {
      "raw": "done",
      "parsed": "done",
      "features": "done",
      "agent": "done",
      "report": "done",
      "knowledge": "pending"
    },
    "warnings": ["options: PRELIM only"],
    "risk_alerts": ["CME PRELIM data"]
  }
}
```

## API Schema (TypeScript)

```typescript
// types/dashboard.ts

interface UnifiedDate {
  trade_date: string;
  modules: string[];
  latest_run_id: string | null;
  has_final_report: boolean;
  has_strategy_card: boolean;
}

interface PipelineStatus {
  raw: "done" | "running" | "pending";
  parsed: "done" | "running" | "pending";
  features: "done" | "running" | "pending";
  agent: "done" | "running" | "pending";
  report: "done" | "running" | "pending";
  knowledge: "done" | "running" | "pending";
}

interface DashboardSummary {
  generated_at: string;
  options: OptionsSummary | null;
  macro: MacroSummary | null;
  pipeline: PipelineStatus;
  warnings: string[];
  risk_alerts: string[];
  latest_reports: ReportItem[];
  data_source_status: Record<string, DataSourceBrief>;
  recent_tasks: TaskItem[];
}

interface StrategyCardData {
  bias: string;
  direction: "bullish" | "bearish" | "neutral";
  confidence: number;
  key_levels: { resistance: number[]; support: number[] };
  triggers: string[];
  invalid_conditions: string[];
  risk_points: string[];
}
```

## 加载状态
- Skeleton: `MetricCardRow` 显示 6 个 pulse 占位卡片
- `ConclusionCard` 显示 "加载中..." + shimmer
- `PipelineStepper` 全部显示 `pending`
- 右侧面板显示 3 个 skeleton panel sections

## 空状态
- 无数据日期：显示 "该日期无分析数据" 提示 + 引导选择其他日期
- 首次使用（无任何日期）：显示 Welcome 引导页

## 错误状态
- API 不可达：显示 ErrorBanner "数据服务不可用" + 重试按钮
- 部分模块 unavailable：对应卡片显示 "Unavailable" badge + 灰色占位
- 网络超时：显示 "请求超时" + 自动重试倒计时

## 验收标准
- [ ] DateSelector 切换日期后，所有卡片同步刷新
- [ ] 结论卡正确显示 Bias / Key Levels / Macro Phase
- [ ] MetricCardRow 6 个指标全部有值或显示 "—"
- [ ] PipelineStepper 步数状态与实际数据一致
- [ ] 右侧面板 Market Bias 区正确显示 Trigger / Invalid / Risk
- [ ] SourceTrace 显示所有数据来源和 snapshot_id
- [ ] unavailable 模块显式标注，不显示虚假数据
- [ ] 响应式：1280px 三列 / 1024px 两列 / 768px 单列
