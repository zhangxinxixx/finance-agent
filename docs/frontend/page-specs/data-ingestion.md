# Data Ingestion Page Spec

## 页面目标
展示所有数据源的接入状态、最近同步时间、数据行数、下次同步时间。支持触发手动同步（P1）。

## 路由
`/data-ingestion`

## 页面模块

```
DataIngestionPage
├── DataSourceGrid            # 数据源卡片网格
│   └── DataSourceCard × N    # 每个数据源一张卡片
│       ├── StatusBadge        # ok / warn / error / unavailable
│       ├── 最后同步时间
│       ├── 下次同步时间
│       ├── 数据行数 / 文件数
│       ├── 数据层级状态 (raw / parsed / analysis_ready)
│       └── SourceTrace 来源标注
├── IngestionPipelineStatus   # 采集流水线总览
└── SourceTrace               # 页面级溯源
```

## 组件树

```
AppShell
└── DataIngestionPage
    ├── IngestionPipelineStatus (shared)
    ├── DataSourceGrid
    │   └── DataSourceCard × N
    │       ├── StatusBadge (shared)
    │       └── SourceTrace (shared, inline)
    └── SourceTrace (shared)
```

## 输入数据

| 数据 | API Endpoint | 类型 |
|------|-------------|------|
| 数据源状态 | `GET /api/data-sources/status` | `DataSourceStatuses` |
| Dashboard 摘要 | `GET /api/dashboard/summary` | `DashboardSummary` (pipeline) |

## Mock 数据文件

`src/mocks/data-ingestion.json`：

```json
{
  "sources": [
    {
      "source_key": "fred_api",
      "source_name": "FRED API",
      "source_group": "macro",
      "source_type": "api",
      "configured": true,
      "raw_ingested": true,
      "parsed": true,
      "analysis_ready": true,
      "latest_raw_time": "2026-05-17T06:00:00Z",
      "latest_parsed_time": "2026-05-17T06:01:00Z",
      "row_count": 2847,
      "status": "ok",
      "error_message": null
    },
    {
      "source_key": "cme_bulletin",
      "source_name": "CME Daily Bulletin",
      "source_group": "cme",
      "source_type": "pdf",
      "configured": true,
      "raw_ingested": true,
      "parsed": true,
      "analysis_ready": true,
      "latest_raw_time": "2026-05-17T02:30:00Z",
      "latest_parsed_time": "2026-05-17T02:31:00Z",
      "row_count": 12480,
      "status": "ok",
      "error_message": null
    },
    {
      "source_key": "treasury_gov",
      "source_name": "Treasury.gov",
      "source_group": "macro",
      "source_type": "scrape",
      "configured": true,
      "raw_ingested": false,
      "parsed": false,
      "analysis_ready": false,
      "latest_raw_time": null,
      "row_count": 0,
      "status": "error",
      "error_message": "TLS certificate expired (2026-05-15)"
    }
  ]
}
```

## API Schema

```typescript
interface DataSourceItem {
  source_key: string;
  source_name: string;
  source_group: string;
  source_type: "api" | "pdf" | "scrape" | "webhook";
  configured: boolean;
  raw_ingested: boolean;
  parsed: boolean;
  analysis_ready: boolean;
  latest_raw_time: string | null;
  latest_parsed_time: string | null;
  row_count: number;
  status: "ok" | "warn" | "error" | "unavailable";
  error_message: string | null;
}

interface DataSourceStatuses {
  sources: DataSourceItem[];
}
```

## 加载状态
- Grid skeleton: 6 张卡片 pulse 动画

## 空状态
- "无已配置数据源" — 引导前往设置页

## 错误状态
- API 不可用：ErrorBanner + 显示上一次缓存的时间戳

## 验收标准
- [ ] 所有数据源正确显示四层状态 (configured/raw/parsed/analysis_ready)
- [ ] 错误数据源显示具体错误信息
- [ ] 数据行数格式化（>1000 加千分位）
- [ ] 时间戳显示为相对时间（"2 小时前"）+ 悬停显示绝对时间
- [ ] SourceTrace 显示数据来源 API 端点
