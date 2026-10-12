# 页面数据边界

React 页面只消费以下三类接口结果：

- `DWS / features`：已加工行情、宏观指标、事件影响、期权结构与研究判断。
- `output`：正式或明确标记状态的报告、可视稿、研究正文和历史版本。
- `ADS operations`：页面可用性、任务状态、质量门槛、调度与加工链路摘要。

`apps/frontend-web/src/adapters/apiClient.ts` 在请求发出前调用 `pageDataBoundary.mjs`。未分类接口默认拒绝；Raw、Parsed、ODS、DWD、文件下载、artifact 内容、任务 logs/events/steps、报告 analysis-inputs、原始金十快讯/日历和按 artifact 追溯均拒绝。页面不得使用另一个 `fetch` 绕过该入口。

页面可以展示来源名、来源方、官方 HTTP(S) URL、数据日期、截至时间、版本、质量状态、快照/运行身份和计数。页面不得展示或复制文件路径、原始响应 JSON、采集正文、解析正文、artifact 内容、提示词/模型原始输入输出。通用依据操作只复制这些允许字段组成的摘要。

## 后端 read model 依赖

Core 集成时需保证下列请求返回过滤后的 read model，而不是给旧响应换名：

| 请求 | 页面用途 | 必须排除 |
|---|---|---|
| `GET /api/data-sources/status?view=ads` | 数据源可用性、时效、下游就绪和官方 URL | raw/parsed 路径、表名、采集响应、artifact 列表 |
| `GET /api/runs?view=ads&limit=20` | 任务列表摘要 | logs/events、输入输出、artifact 内容 |
| `GET /api/runs/{run_id}?view=ads` | 单次运行与步骤状态摘要 | logs/events payload、input/output JSON、文件路径 |
| `GET /api/processing/*?view=ads` | 加工覆盖、质量门槛、绑定和血缘摘要 | artifact 路径、原始输入、解析内容 |
| `GET /api/events/calendar-summary` | 市场监控中的已加工事件日历 | 原始日历响应和采集字段 |
| `POST /dagster/graphql` | 调度拓扑、运行、步骤状态和计划摘要 | run config、错误 stack、step message 正文 |

其中 `events/calendar-summary` 是本次新增的后端 read model；其响应沿用当前日历展示字段：`generated_at`、`status`、`stats`、`freshness` 和 `events[]`，事件仅含标题、发布时间、重要性、公布值/预期值/前值及影响摘要。

现有报告正文、DWS 图表、专题分析、历史报告、原研究与当前背景的独立身份、时点/有效期、质量阻断和失败提示继续保留。外部链接只允许用户点击官方来源，不作为页面数据请求。

## 独立 TradingView 看盘例外

黄金工作区和市场监控共用 `TradingViewChart`，仅允许嵌入固定 `https://www.tradingview.com/widgetembed/` 域的独立看盘 iframe。symbol 固定为 `OANDA:XAUUSD`，默认 15m，周期仅可切换 15m / 1h / 4h；新窗口链接也固定为 TradingView。浅色主题与页面保持一致。

这是用户明确授权的外部展示例外，不开放任意外部 fetch，也不改变系统 API 的 DWS / output / ADS 白名单或 Raw / ODS / DWD 禁令。外部图表不读取本地 `/api/market/candles`，不触发自有采集，不通过消息或抓取把图表数据送入研究输入、策略或 DWD。市场历史指标与图例继续读取既有系统 read model。

iframe 加载只表示文档加载，不能证明行情可用性、延迟或质量。超时或错误时显示说明，始终保留新窗口链接；切换周期替换唯一 iframe，卸载清理计时器。
