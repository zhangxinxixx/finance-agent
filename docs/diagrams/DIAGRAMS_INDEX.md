# Mermaid 图索引

本目录的 `.mmd` 图用于 Markdown 文档或文档站渲染。

| 图 | 用途 |
| --- | --- |
| `system-architecture.mmd` | 系统总体架构：前端、API、调度器、任务执行器、流水线、数据库、文件存储 |
| `data-flow.mmd` | 数据从外部源进入原始层、解析层、特征层、分析层、报告和前端页面的流向 |
| `backend-pipeline.mmd` | 当前盘前任务后端主链和 C4 分析流水线的位置 |
| `report-artifacts-flow.mmd` | 报告四类产物：原文、分析正文、可视化报告、结构化 JSON 的生成流程 |
| `agent-flow.mmd` | 领域 Agent、协调器、事实复核、综合分析之间的关系 |
| `frontend-page-map.mmd` | Vite React 当前页面路由图 |
| `source-trace-flow.mmd` | 原始文件 -> 解析文件 -> 快照 -> Agent 输出 -> 报告 / 策略卡片的溯源链路 |
| `news-pipeline-flow.mmd` | 新闻数据源采集、事件分类、行情反应、follow-up 任务和日报输出链路 |

说明：

- 图中 `NEED_VERIFY` 表示代码中存在模块或 API，但是否已稳定进入每日主链仍需真实 run 验证。
- `/dashboard` FastAPI 兼容跳转未画成前端主入口；当前主入口是 `apps/frontend-web/src/main.tsx` 中的 Vite 路由。
