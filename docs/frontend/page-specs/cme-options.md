# CME Options Page Spec

## 页面目标
展示 CME 黄金期权结构分析：Gamma Exposure (GEX)、期权墙位评分、关键价位地图、机构持仓意图、到期月对比。

## 路由
`/cme-options`

## 页面模块

```
CMEOptionsPage
├── DateSelector              # 日期选择器
├── OptionsSummaryBar         # 顶部摘要条
│   ├── 产品 (GC)
│   ├── 到期月列表
│   ├── 数据版本 (FINAL / PRELIM)
│   └── 数据行数
├── GammaZeroCard             # Gamma Zero 价位卡
│   ├── GZ Price
│   ├── GZ Method
│   └── Net GEX 方向
├── OptionsWallTable          # 墙位评分表 (Top 10)
│   ├── TanStack Table 列
│   │   ├── Strike
│   │   ├── Wall Type (Call Wall / Put Wall)
│   │   ├── OI
│   │   ├── ΔOI (多日变化)
│   │   ├── Wall Score
│   │   └── PNT (Put/Call Normalized Total)
│   └── 排序/筛选
├── KeyLevelMap               # 关键价位地图
│   ├── 上方 Call 压制区
│   ├── 下方 Put 支撑区
│   ├── Pin 位
│   └── 突破门槛
├── ExpiryComparison          # 到期月对比 (近月 vs 次月)
│   ├── GEX 变化
│   ├── Wall Migration
│   └── Roll Detection
└── SourceTrace               # 页面级溯源
```

## 组件树

```
AppShell
└── CMEOptionsPage
    ├── DateSelector (shared)
    ├── OptionsSummaryBar
    │   └── StatusBadge (shared)
    ├── GammaZeroCard
    │   └── MetricCard (shared)
    ├── OptionsWallTable
    │   └── TanStack Table
    ├── KeyLevelMap
    │   ├── CallZoneCard
    │   ├── PutZoneCard
    │   └── PinLevelCard
    ├── ExpiryComparison
    └── SourceTrace (shared)
```

## 输入数据

| 数据 | API Endpoint | 类型 |
|------|-------------|------|
| CME 期权快照 | `GET /api/options/snapshot?date=X` | `OptionsSnapshot` |
| 日期列表 | `GET /api/reports/dates` | `UnifiedDatesResponse` |

## Mock 数据文件

`src/mocks/cme-options.json`：

```json
{
  "trade_date": "2026-05-17",
  "data_source": {
    "product": "GC",
    "status": "PRELIM",
    "expiries": ["2026-06", "2026-08", "2026-10"],
    "row_count": 12480
  },
  "parameters": {
    "f_value": 3265.40,
    "r_value": 0.043
  },
  "gex": {
    "netgex_aggregate": {
      "net_gex": 125000000,
      "net_gex_direction": "positive",
      "gamma_zero": {
        "price": 3225.50,
        "method": "weighted-average"
      }
    }
  },
  "wall_scores": [
    { "strike": 3300, "wall_type": "Call Wall", "oi": 15420, "delta_oi": 320, "wall_score": 0.87, "pnt": 0.72 },
    { "strike": 3250, "wall_type": "Call Wall", "oi": 12840, "delta_oi": -150, "wall_score": 0.74, "pnt": 0.61 },
    { "strike": 3200, "wall_type": "Put Wall", "oi": 18320, "delta_oi": 560, "wall_score": 0.91, "pnt": 0.85 },
    { "strike": 3150, "wall_type": "Put Wall", "oi": 11200, "delta_oi": -80, "wall_score": 0.65, "pnt": 0.53 }
  ],
  "support_resistance": {
    "resistance": [
      { "strike": 3300, "wall_score": 0.87, "distance_pct": 1.02 },
      { "strike": 3250, "wall_score": 0.74, "distance_pct": -0.47 }
    ],
    "support": [
      { "strike": 3200, "wall_score": 0.91, "distance_pct": -1.98 },
      { "strike": 3150, "wall_score": 0.65, "distance_pct": -3.54 }
    ]
  },
  "intent": {
    "type": "neutral-bullish",
    "confidence": 0.62
  },
  "calibration": {
    "oi_deltas_available": true,
    "wall_migration_detected": false,
    "expiry_roll_detected": false,
    "findings": ["Near-month OI concentrated at 3200-3300 range"]
  }
}
```

## API Schema

```typescript
interface WallScore {
  strike: number;
  wall_type: "Call Wall" | "Put Wall";
  oi: number;
  delta_oi: number | null;
  wall_score: number;
  pnt: number;
}

interface OptionsSnapshot {
  trade_date: string;
  data_source: {
    product: string;
    status: "FINAL" | "PRELIM";
    expiries: string[];
    row_count: number;
  };
  parameters: {
    f_value: number;
    r_value: number;
  };
  gex: {
    netgex_aggregate: {
      net_gex: number;
      net_gex_direction: string;
      gamma_zero: {
        price: number;
        method: string;
      };
    };
  };
  wall_scores: WallScore[];
  support_resistance: {
    resistance: LevelItem[];
    support: LevelItem[];
  };
  intent: {
    type: string;
    confidence: number;
  };
  calibration?: {
    oi_deltas_available: boolean;
    wall_migration_detected: boolean;
    findings: string[];
  };
}
```

## 加载状态
- OptionsSummaryBar: skeleton 行
- GammaZeroCard: skeleton 卡片
- OptionsWallTable: 10 行 skeleton table
- KeyLevelMap: 3 张 skeleton 卡片

## 空状态
- 无 CME 数据：显示 "该日期无 CME 期权数据" + 引导运行 premarket
- PRELIM 数据：顶部显式显示 "⚠️ PRELIM data — FINAL preferred" banner

## 错误状态
- API 不可用：ErrorBanner + 上次可用时间
- 部分字段缺失：对应单元格显示 "—" 而非 0

## 验收标准
- [ ] 顶部摘要条正确显示产品/到期月/版本/行数
- [ ] GammaZero 显示价格和方法
- [ ] 墙位表正确排序（默认按 wall_score 降序）
- [ ] Call Wall / Put Wall 颜色区分
- [ ] ΔOI 正值绿色、负值红色
- [ ] 关键价位地图显示 Call/Put 压制/支撑区
- [ ] PRELIM 数据显式标注
- [ ] SourceTrace 显示 CME 数据来源和 snapshot_id
