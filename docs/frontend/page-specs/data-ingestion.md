# Data Ingestion Page Spec

## 页面目标
展示所有数据源的接入状态、最近同步时间、数据行数、下次同步时间。支持触发手动同步（P1）。

## 视觉模板

数据接入页归入 `列表/管理模板` 的运维矩阵变体：

```text
页面状态头
关键阻断 Banner
阶段健康条
数据源健康矩阵 + 右侧数据源详情/操作入口/阻断问题
Pipeline 日志
```

视觉规则：

- 页头使用中文主标题，不使用装饰性英文 eyebrow。
- 页头副标题保持一句话，说明用途即可，不写开发者视角说明。
- `可用/待处理/数据日期/最近运行` 使用 badge 化 meta，不再用分隔线小字。
- 阶段状态、数据源类型、延迟天数、操作按钮最低字号为 `10px`；状态和按钮优先使用 `11px`。
- 表头、分组标题、右侧面板标题最低 `12px`，禁止继续使用 `8px/9px` 作为核心扫描信息。
- 数据源名称若截断，必须提供 `title` tooltip。
- `Pipeline 日志` 是辅助模块，但标题、来源名称、时间戳仍需可读；默认不使用 8px 时间戳。

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
