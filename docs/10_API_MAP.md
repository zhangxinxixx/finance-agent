# API 映射

> 事实源：`apps/api/routes/*.py`，代码基线：2026-07-21。下表按能力分组，同一路由族的参数变体合并展示。

## Health、Dashboard 与运行

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/health`、`/api/health` | 健康检查 |
| GET | `/api/dashboard/summary` | Dashboard read model |
| GET | `/api/pipelines/premarket/contract` | 盘前拓扑 contract |
| GET | `/api/pipelines/premarket/readiness` | source readiness |
| GET | `/api/tasks/premarket/preflight` | 手动触发预检 |
| POST | `/api/tasks/premarket` | 通过 Dagster 启动盘前 run |
| GET | `/api/tasks/{task_id}`、`/api/tasks/{task_id}/logs` | 兼容任务视图 |
| GET | `/api/runs` | canonical run 列表 |
| GET | `/api/runs/{run_id}` | canonical run 详情 |
| GET | `/api/runs/{run_id}/steps`、`/logs`、`/artifacts`、`/events` | run 下钻 |
| GET | `/api/artifacts/{artifact_id}` | artifact 详情 |

## 数据源、市场和领域 read models

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/data-sources/status`、`/registry`、`/health` | 数据源状态与健康 |
| GET | `/api/data-sources/{source_key}/history`、`/api/data-status/summary` | 来源历史与汇总 |
| POST | `/api/ingestion/sources/{source_key}/retry`、`/test` | 重试与测试数据源 |
| POST | `/api/ingestion/manual-upload` | 受控手工上传 |
| GET | `/api/market/tickers`、`/monitor`、`/monitor/history`、`/candles` | 市场行情 read models |
| GET | `/api/macro/latest`、`/api/macro/report` | 宏观数据与报告 |
| GET | `/api/options/snapshot`、`/decision`、`/report`、`/dates`、`/visual-report*` | CME 期权 |
| GET | `/api/market-odds/snapshot`、`/report`、`/external/latest` | 市场赔率 |
| GET | `/api/jin10/quotes/latest`、`/calendar`、`/flash`、`/kline` | 金十市场数据 |
| GET | `/api/gold/mainlines/latest`、`/api/gold/mainlines` | Gold mainlines |
| GET | `/api/gold/runtime-orchestration/contract`、`/preview` | Gold runtime orchestration |

## 报告、策略与评估

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/reports/index`、`/dates`、`/{report_id}` | 报告列表与详情 |
| GET | `/api/reports/{report_id}/artifacts`、`/source`、`/evidence`、`/analysis-inputs` | 报告 lineage |
| GET | `/api/reports/{report_id}/analysis`、`/visual` | 报告分析与可视化 |
| GET | `/api/final-report/latest`、`/api/final-report` | accepted final report |
| GET | `/api/strategy-card/latest`、`/api/strategy-card` | accepted strategy card |
| GET | `/api/strategy-cards`、`/assets`、`/latest`、`/{strategy_card_id}` | 策略卡历史与详情 |
| GET | `/api/live-strategy/latest`、`/history` | 实时策略 |
| GET | `/api/shadow-evaluation/history`、`/metrics/latest`、`/metrics` | 影子评估 |
| GET | `/api/jin10/daily-report*`、`/weekly-report*`、`/report-bundle*` | 金十报告 |
| GET | `/api/news/daily-analysis-triggers*`、`/daily-brief*`、`/daily-analysis-followups*` | 新闻分析 |

## Event、trace 与 processing

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/events/flow/overview`、`/briefs`、`/report-inputs` | Event Flow 总览 |
| GET | `/api/events/{event_id}`、`/impact`、`/market-reaction` | Event 下钻 |
| POST | `/api/events/*/link`、`/ignore`、`/include`、`/exclude`、`/review` | Event action |
| GET | `/api/source-trace/{snapshot_id}`、`/by-report`、`/by-strategy`、`/by-artifact` | Source trace |
| GET | `/api/processing/overview` | ProcessingMonitor 总览 |
| GET | `/api/processing/trace/*` | 按 trace/event/input/source-ref/mainline/chain 下钻 |

## Agent、复核与治理

| Method | Path | 用途 |
| --- | --- | --- |
| GET/POST | `/api/agent-analysis/latest`、`/query`、`/inspect`、`/synthesis/latest`、`/run` | Agent analysis |
| GET/POST | `/api/agents/registry*`、`/prompts*`、`/feedback*` | Agent registry 与 prompt governance |
| GET/POST | `/api/reviews`、`/{review_id}`、`/approve`、`/reject`、`/rerun`、`/use-fallback` | 人工复核 |
| GET | `/api/llm/audits`、`/api/llm/audits/{audit_id}` | 受权限保护的 LLM 审计 |
| GET/POST | `/api/governance/system-evolution/latest`、`/proposal/action` | 系统演进治理 |
| GET/POST | `/api/orchestration/latest`、`/notification-plan`、`/manual-review/action` | 编排与复核动作 |

## Knowledge、Playbook 与设置

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/api/knowledge/items`、`/api/knowledge/items/{item_id}` | 知识条目 |
| GET | `/api/playbooks`、`/{playbook_id}`、`/versions` | Playbook 与版本 |
| GET/POST | `/api/settings/status`、`/history`、`/preferences`、`/sources`、`/secrets` | 受控设置与审计 |

## 兼容路由

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/dashboard`、`/reports`、`/event-flow`、`/knowledge-base`、`/scheduler`、`/settings` | 重定向到 Vite 主线 |
| GET/POST | `/tasks/*` | `/api/tasks/*` 兼容别名 |

新客户端应优先使用 `/api/*` contract；兼容路由不是新功能入口。
