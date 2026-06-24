# API 映射

来源：`apps/api/main.py`

## Core

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/memory/context` | 本地研究上下文 |

## Tasks / Runs

| Method | Path | 页面 |
| --- | --- | --- |
| POST | `/tasks/premarket` | 兼容任务触发 |
| POST | `/api/tasks/premarket` | Run / 手动触发 |
| GET | `/tasks/{task_id}` | 兼容任务详情 |
| GET | `/api/tasks/{task_id}` | 任务详情 |
| GET | `/tasks/{task_id}/logs` | 兼容任务日志 |
| GET | `/api/tasks/{task_id}/logs` | 任务日志 |
| GET | `/api/tasks` | 最近任务 |
| GET | `/api/runs` | Agent Tasks |
| GET | `/api/runs/{run_id}` | Agent Task Detail |
| GET | `/api/runs/{run_id}/steps` | Agent Task Detail |
| GET | `/api/runs/{run_id}/logs` | Agent Task Detail |
| GET | `/api/runs/{run_id}/artifacts` | Agent Task Detail |

## SourceTrace

| Method | Path | 页面 |
| --- | --- | --- |
| GET | `/api/source-trace/{snapshot_id}` | Report Detail / Strategy / Agent Tasks |
| GET | `/api/source-trace/by-report/{report_id}` | Report Detail |
| GET | `/api/source-trace/by-strategy/{strategy_card_id}` | Strategy Center |

## Dashboard / Data

| Method | Path | 页面 |
| --- | --- | --- |
| GET | `/api/dashboard/summary` | Dashboard |
| GET | `/api/data-sources/status` | Data Ingestion |
| GET | `/api/data-status/summary` | Data Ingestion / Global status |
| POST | `/api/ingestion/sources/{source_key}/retry` | Data Ingestion |
| POST | `/api/ingestion/manual-upload` | Data Ingestion |

## Review

| Method | Path | 页面 |
| --- | --- | --- |
| GET | `/api/reviews` | Review Center / Agent Tasks |
| GET | `/api/reviews/{review_id}` | Review detail |
| POST | `/api/reviews/{review_id}/approve` | Review action |
| POST | `/api/reviews/{review_id}/reject` | Review action |
| POST | `/api/reviews/{review_id}/rerun` | Review action |
| POST | `/api/reviews/{review_id}/use-fallback` | Review action |

## Market / Macro / CME

| Method | Path | 页面 |
| --- | --- | --- |
| GET | `/api/market/tickers` | Market Monitor |
| GET | `/api/market/monitor` | Market Monitor |
| GET | `/api/market/monitor/history` | Market Monitor |
| GET | `/api/macro/latest` | Dashboard / Market Monitor |
| GET | `/api/macro/report` | Reports |
| GET | `/api/options/snapshot` | CME Options |
| GET | `/api/options/report` | Reports |
| GET | `/api/options/dates` | CME Options / Reports |
| GET | `/api/options/visual-report/latest` | Reports |
| GET | `/api/options/visual-report` | Reports |
| GET | `/api/market-odds/snapshot` | Market Monitor / Agent |
| GET | `/api/market-odds/report` | Reports |

## Reports / Strategy

| Method | Path | 页面 |
| --- | --- | --- |
| GET | `/api/reports/index` | Reports |
| GET | `/api/reports/dates` | Reports / Dashboard |
| GET | `/api/reports/{report_id}` | Report Detail |
| GET | `/api/reports/{report_id}/artifacts` | Report Detail |
| GET | `/api/reports/{report_id}/source` | Report Detail |
| GET | `/api/reports/{report_id}/analysis` | Report Detail |
| GET | `/api/reports/{report_id}/visual` | Report Detail |
| GET | `/api/reports/{report_id}/evidence` | Report Detail |
| GET | `/api/reports/{report_id}/analysis-inputs` | Report Detail |
| GET | `/api/final-report/latest` | Dashboard / Reports legacy |
| GET | `/api/final-report` | Reports legacy |
| GET | `/api/strategy-card/latest` | Dashboard legacy |
| GET | `/api/strategy-card` | Reports legacy |
| GET | `/api/strategy-cards` | Strategy Center |
| GET | `/api/strategy-cards/assets` | Strategy Center |
| GET | `/api/strategy-cards/latest` | Strategy Center |
| GET | `/api/strategy-cards/{strategy_card_id}` | Strategy Center |

## Jin10

| Method | Path | 页面 |
| --- | --- | --- |
| GET | `/api/jin10/daily-report/latest` | Reports |
| GET | `/api/jin10/daily-report` | Reports |
| GET | `/api/jin10/weekly-report/latest` | Reports |
| GET | `/api/jin10/weekly-report` | Reports |
| GET | `/api/jin10/report-bundle/latest` | Reports |
| GET | `/api/jin10/report-bundle` | Reports |
| GET | `/api/jin10/report-bundle/{date}/{run_id}/asset/{asset_path:path}` | Reports assets |
| GET | `/api/jin10/quotes/latest` | Dashboard / Market Monitor |
| GET | `/api/jin10/calendar` | Event Flow |
| GET | `/api/jin10/flash` | Event Flow |

## Event / Knowledge / Settings / Agent

| Method | Path | 页面 |
| --- | --- | --- |
| GET | `/api/events/flow/overview` | Event Flow |
| GET | `/api/knowledge/items` | Knowledge Base |
| GET | `/api/knowledge/items/{item_id}` | Knowledge detail |
| POST | `/api/playbooks` | Settings / Knowledge |
| GET | `/api/playbooks` | Settings |
| GET | `/api/playbooks/{playbook_id}` | Settings |
| GET | `/api/playbooks/{playbook_id}/versions` | Settings |
| GET | `/api/settings/status` | Settings |
| POST | `/api/settings/preferences` | Settings |
| POST | `/api/settings/preferences/reset` | Settings |
| POST | `/api/settings/sources/{source_key}` | Settings |
| POST | `/api/settings/sources/{source_key}/reset` | Settings |
| POST | `/api/settings/secrets/{source_key}` | Settings |
| POST | `/api/settings/secrets/{source_key}/reset` | Settings |
| GET | `/api/settings/history` | Settings Audit |
| POST | `/api/settings/history/{audit_id}/rollback` | Settings Audit |
| GET | `/api/agents/registry` | Settings |
| GET | `/api/agents/registry/{agent_id}` | Settings |
| GET | `/api/agents/prompts` | Settings |
| GET | `/api/agents/prompts/{agent_id}` | Settings |
| GET | `/api/agents/prompts/{agent_id}/active` | Settings |
| POST | `/api/agents/prompts/{agent_id}` | Settings |
| PATCH | `/api/agents/prompts/{agent_id}/activate` | Settings |
| POST | `/api/agents/feedback` | Settings |
| GET | `/api/agents/feedback/{agent_id}` | Settings |
| GET | `/api/agents/feedback` | Settings |
| GET | `/api/agent-analysis/latest` | Agent Analysis |
| GET | `/api/agent-analysis` | Agent Analysis |
| GET | `/api/agent-analysis/inspect` | Agent Tasks |
| GET | `/api/agent-analysis/synthesis/latest` | Agent Analysis |
| POST | `/api/agent-analysis/run` | Agent manual run |

## Frontend compatibility

| Method | Path | 用途 |
| --- | --- | --- |
| GET | `/dashboard` | 307 跳转到 Vite `/dashboard` |
| GET | `/dashboard/system-status` | 轻量系统状态 |
